import requests
import xml.etree.ElementTree as ET
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import warnings
import json
import urllib.parse

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

def _query_data(_query):
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
    cursor.execute(_query)
    results = cursor.fetchall()
    cursor.close()
    data = pd.read_sql_query(_query, _conn)
    df = pd.DataFrame(data)
    _conn.close()
    return df

def Get_project_Data(_query):
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
    # _query = f"SELECT DISTINCT NAME, Table_Name, Destination \
    #             FROM [Pre].[Lookup_Tables]"
    cursor.execute(_query)
    dict_projects = {}
    for row in cursor:
        project = row[0]
        sub_site = row[1]
        dict_projects[project] = sub_site
    cursor.close()
    _conn.close()
    return dict_projects

def pull_data_from_sharepoint(sub_site, url):
    _service_document_location = f"{_site}/{sub_site}/_api/web/GetFileByServerRelativeUrl(@url)/ListItemAllFields?@url='{url}'"
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
                        WHERE Table_Type = 'Document Library - Project lvl' AND _Source <> 'Project Schedule Template - نماذج خطة المشروع' \
                        ORDER BY _Source")

all_data = pd.DataFrame()
combined_df = pd.DataFrame()
not_found_df = pd.DataFrame(columns=['PID', 'List'])

for list_name in all_lists:
    warnings.filterwarnings("ignore")

    df_list = []
    
    all_projects = _query_data(f"SELECT DISTINCT ProjectId \
		                    ,	SUBSTRING(ProjectWorkspaceInternalUrl, CHARINDEX('/VRO/', ProjectWorkspaceInternalUrl) + LEN('/VRO/'), LEN(ProjectWorkspaceInternalUrl)) AS Sub_Site \
		                    ,	T2.serverrelativeurl \
                            ,   T2.[name] \
                            FROM [Pre].[ProjectsByTaples] T1 \
                                INNER JOIN DOC_PSLvl.[{list_name}] T2 \
                                    ON T1.ProjectId = T2.pid \
                            ORDER BY Sub_Site")

    for index, row in all_projects.iterrows():
        #print(f"{list_name} >> {project} >> {sub_site}")
        try:
            server_url = row['serverrelativeurl']
            #server_url = server_url.replace("'", "%27")
            encoded_url = urllib.parse.quote(server_url.replace("'", "%27"))
            #print(encoded_url)
            df = pull_data_from_sharepoint(row['Sub_Site'], encoded_url)
            df['PID'] = row['ProjectId']
            df['fileurl'] = row['serverrelativeurl']
            if df.empty:
                print(f"No data found for list {list_name} on SharePoint. Skipping...")
                continue
                
            df_list.append(df)
            print(f"File {row['name']} metadata from list {list_name} fetched successfully from sub_site {row['Sub_Site']}")
            
        except:
            print(f"Error fetching data for list {list_name} @ {row['name']}")
            print(f"No data found for list {list_name} on SharePoint in sub_site {row['Sub_Site']} @ {row['name']}. Skipping...")
            not_found_df = not_found_df._append({'Project': row['serverrelativeurl'], 'List': list_name}, ignore_index=True)
    
    if len(df_list) > 0:
        merged_df = pd.concat(df_list)
        merged_df.columns = merged_df.columns.str.lower()  # Change column names to lowercase
        combined_df = combined_df._append(merged_df)
        
        create_table_from_csv(merged_df, f"{list_name}_metadata", 'DOC_PSLvl')
        insert_data_into_table(merged_df, f"{list_name}_metadata", 'DOC_PSLvl')
        print(f"List {list_name} migrated successfully into DOC_PSLvl.{list_name}")