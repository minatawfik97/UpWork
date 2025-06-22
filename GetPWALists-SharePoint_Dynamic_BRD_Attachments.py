import requests
import xml.etree.ElementTree as ET
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import json
import warnings

warnings.filterwarnings('ignore')

with open("config.json", "r") as config_file:
    config = json.load(config_file)

database_config = config['staging_db']
sharepoint_config = config['sharepoint_source']

# Database
_server = database_config['server']
_database = database_config['database']
_user = database_config['user']
_pw = database_config['password']
conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};\
            SERVER={_server};\
            DATABASE={_database};\
            UID={_user};\
            PWD={_pw};\
            CHARSET=utf8;COLLATION=Arabic_CI_AI'

# SharePoint
_username = sharepoint_config['username']
_password = sharepoint_config['password']
_site = sharepoint_config['site']

def query_data(query):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()
    data = pd.read_sql_query(query, conn)
    df = pd.DataFrame(data)
    conn.close()
    return [item[0] for item in results]


def pull_data_from_sharepoint(list_name):
    site = f'{_site}/BRD'
    _service_document_location = f"{site}/_api/web/lists/getbytitle('{list_name}')/items?$expand=AttachmentFiles&$select=AttachmentFiles&$Top=5000"
    response = requests.get(_service_document_location, auth=HttpNtlmAuth(_username, _password), verify=False)
    if response.status_code == 200:
        xml_string = response.content
    else:
        print("Error")

    data = []

    root = ET.fromstring(xml_string)

    for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
        entry_data = {}
        for elem in entry.iter():
            if elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or elem.tag.endswith('title'):
                value = elem.text                
                entry_data[elem.tag.split('}')[1].lower()] = value  # Change column name to lowercase
        data.append(entry_data)

    # Check if there are more pages
    next_link = root.find('{http://www.w3.org/2005/Atom}link[@rel="next"]')
    if next_link is not None:
        _service_document_location = next_link.get('href')
    else:
        _service_document_location = None

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.loc[:, ~df.columns.duplicated()]
    else:
        df = pd.DataFrame()
    return df

def table_exists(cursor, table_name, _schema):
    cursor.execute(f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES \
                        WHERE TABLE_NAME = '{table_name}' \
                        AND TABLE_SCHEMA = '{_schema}'")
    return cursor.fetchone()[0] != 0

def create_table_from_csv(df, table_name, _schema):
    #df = pd.read_csv(csv_file)
    df.columns = df.columns.str.lower()  # Change column names to lowercase
    df = df.loc[:, ~df.columns.duplicated()]

    column_names = df.columns.tolist()
    column_types = df.dtypes.tolist()

    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    if table_exists(cursor, table_name, _schema):
        cursor.execute(f"DROP TABLE [{_schema}].[{table_name}]")

    create_table_query = f"CREATE TABLE [{_schema}].[{table_name}] ("
    for column_name, column_type in zip(column_names, column_types):
        if column_type == 'int64':
            sql_type = 'NVARCHAR(MAX)'
        elif column_type == 'float64':
            sql_type = 'NVARCHAR(MAX)'
        else:
            sql_type = 'NVARCHAR(MAX)'
        create_table_query += f"[{column_name}] {sql_type}, "
    create_table_query = create_table_query.rstrip(', ') + ");"

    cursor.execute(create_table_query)
    conn.commit()

    cursor.close()
    conn.close()
    print(f"Table '{_schema}'.'{table_name}' created successfully")

def insert_data_into_table(df, table_name, _schema):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(df.columns))
    insert_sql = f"INSERT INTO [{_schema}].[{table_name}] VALUES ({placeholders})"

    for row in df.itertuples(index=False):
        # Convert and validate data types
        processed_row = []
        for value in row:
            if isinstance(value, float) and pd.isnull(value):
                processed_row.append(None)  # Replace NaN values with None
            elif isinstance(value, pd.Timestamp):  # Handle datetime values if needed
                processed_row.append(value.strftime('%Y-%m-%d %H:%M:%S'))
            else:
                processed_row.append(value)
        
        try:
            cursor.execute(insert_sql, processed_row)
        except pyodbc.Error as e:
            print(f"Error inserting row: {row}")
            print(f"Error message: {e}")
    conn.commit()
    conn.close()
    print(f"Data inserted successfully into {_schema}.{table_name}")

all_lists = query_data("SELECT DISTINCT _Source \
                        FROM Mapping.Unified_Mapping \
                        WHERE Table_Type = 'PWA List' AND _Source = 'مزودي الخدمة'\
                        ORDER BY _Source")

for list_name in all_lists:
    warnings.filterwarnings("ignore")
    try:
        df = pull_data_from_sharepoint(list_name)
        if df.empty or (df.shape[1] == 1 and df.iloc[:, 0].isnull().all()):
            print(f"No data found or only column title with None values for list {list_name} on SharePoint. Skipping...")
            continue
        
        #file_path = f'D:\MOF_Migration\Lists\{list_name}_Attachments.csv'
        #df.to_csv(file_path, index=False, mode='w')
        create_table_from_csv(df, f"{list_name}_Attachments", 'DOC_RTLvl')
        insert_data_into_table(df, f"{list_name}_Attachments", 'DOC_RTLvl')
        print(f"List {list_name} migrated successfully")
    except Exception as e:
        print(f"Error migrating list {list_name}: {str(e)}")