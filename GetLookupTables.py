import requests
import xml.etree.ElementTree as ET
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import warnings
import json

warnings.filterwarnings("ignore")

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

database_config = config['staging_db']
sharepoint_config = config['sharepoint_source_projectserver']
staging_dir = config['staging_directory']

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

# ProjectServer
_list = "Lookup"
_username = sharepoint_config['username']
_password = sharepoint_config['password']
_service_document_location = sharepoint_config['lookup']

def _pull_data_from_sharepoint():
    response = requests.get(_service_document_location, auth=HttpNtlmAuth(_username, _password), verify=False)
    if response.status_code == 200:
        xml_string = response.content
    else:
        print("Error")
            
    _data = []

    _root = ET.fromstring(xml_string)

    for _entry in _root.iter('{http://www.w3.org/2005/Atom}entry'):
        entry_data = {}
        for _elem in _entry.iter():
            if _elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or _elem.tag.endswith('title'):
                value = _elem.text                
                entry_data[_elem.tag.split('}')[1]] = value
        _data.append(entry_data)

    _df = pd.DataFrame(_data)
    selected_columns = ['Description', 'FullValue', 'InternalName', 'Value', 'Name']
    _df = _df[selected_columns]

    return(_df)

def table_exists(cursor, table_name):
    cursor.execute(f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{table_name}'")
    return cursor.fetchone()[0] != 0

def create_table_from_csv(df, table_name):
    #df = pd.read_csv(csv_file)
    column_names = df.columns.tolist()
    column_types = df.dtypes.tolist()

    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    if table_exists(cursor, table_name):
        cursor.execute(f"DROP TABLE {table_name}")

    create_table_query = f"CREATE TABLE {table_name} ("
    for column_name, column_type in zip(column_names, column_types):
        if column_type == 'int64':
            sql_type = 'NVARCHAR(MAX)'
        elif column_type == 'float64':
            sql_type = 'NVARCHAR(MAX)'
        else:
            sql_type = 'NVARCHAR(MAX)'
        create_table_query += f"{column_name} {sql_type}, "
    create_table_query = create_table_query.rstrip(', ') + ");"

    cursor.execute(create_table_query)
    conn.commit()

    cursor.close()
    conn.close()
    print(f"Table '{table_name}' created successfully")

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

df = _pull_data_from_sharepoint()
df['RN'] = range(1, len(df) + 1)
create_table_from_csv(df, _list)
insert_data_into_table(df, _list, 'dbo')