import requests
from requests_ntlm import HttpNtlmAuth
import pyodbc
import json
import os
import warnings
import pandas as pd

warnings.filterwarnings("ignore")

with open("config.json", "r") as config_file:
    config = json.load(config_file)

sharepoint_config = config["documents"]
database_config = config['staging_db']
staging_dir = config['staging_directory']

site_url = sharepoint_config["site"]
username = sharepoint_config["username"]
password = sharepoint_config["password"]
xsite = sharepoint_config["password"]
#local_download_directory = sharepoint_config["local_download_directory"]

#Stading Dir
_partition_name = staging_dir["partition"]
_folder = staging_dir["Folder"]

# Database
_server = database_config['server']
_database = database_config['database']
_user = database_config['user']
_pw = database_config['password']
conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};' \
            f'SERVER={_server};' \
            f'DATABASE={_database};' \
            f'UID={_user};' \
            f'PWD={_pw};' \
            f'COLLATION=Arabic_CI_AS'

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

def create_folders(partition, folder, subfolder):
    migration_path = os.path.join(partition, folder)

    subfolder_path = os.path.join(migration_path, subfolder)
    try:
        os.makedirs(migration_path, exist_ok=True)
        os.makedirs(subfolder_path, exist_ok=True)
        print(f"Folders created successfully at {subfolder_path}")
    except Exception as e:
        print(f"An error occurred: {e}")
    return subfolder_path

#create_folders('D:\\', 'XMigration', 'Subsite')

#local_staging_directory = create_folders(_partition_name, _folder, "lists")

def Get_Documents(_query):
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
    # _query = f"SELECT DISTINCT serverrelativeurl \
    #             FROM dbo.Documents"
    cursor.execute(_query)
    results = cursor.fetchall()
    docs_url = [row[0] for row in results]
    cursor.close()
    _conn.close()
    return docs_url

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

doc_sites = ['Documents']

auth = HttpNtlmAuth(username, password)

not_migrated_df = pd.DataFrame(columns=['Library', 'file_name', 'file_url'])

for _table in doc_sites:
    mainfolder = create_folders(_partition_name, _folder, "RT_Documents")

    doc_files = _query_data(f"SELECT    serverrelativeurl, [name] \
		                            ,	IIF(ROW_NUMBER() OVER (PARTITION BY [NAME] ORDER BY serverrelativeurl) > 1, CONCAT(id, '_', [name]), [name]) AS sec_name \
                            FROM Transformed_RTAttachments")
    
    for index, row in doc_files.iterrows():
        file_path = row['serverrelativeurl']
        #local_download_directory = f"{_partition_name}{_folder}\{_table}"
        file_url = site_url + file_path
        file_name = row['sec_name']

        local_download_directory = create_folders(_partition_name, f"{_folder}\\", "RT_Documents")

        local_file_path = os.path.join(local_download_directory, file_name)

        try:
            response = requests.get(file_url, auth=auth, verify=False, stream=True, timeout=480)

            if response.status_code == 200:
                with open(local_file_path, 'wb') as local_file:
                    for chunk in response.iter_content(chunk_size=4096):
                        if chunk:
                            local_file.write(chunk)
                print(f"File '{file_name}' downloaded to '{local_file_path}'")
            else:
                print(f"Failed to download file. Status code: {response.status_code}")
                not_migrated_df = not_migrated_df._append({'Library': f"RT_{_table}", 'file_name': file_name, 'file_url': file_path}, ignore_index=True)
                
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during the request: {e}")
            not_migrated_df = not_migrated_df._append({'Library': f"RT_{_table}", 'file_name': file_name, 'file_url': file_path}, ignore_index=True)

    if not_migrated_df.empty:
        print("All Documents Downloaded.")
    else:
        insert_data_into_table(not_migrated_df, 'Not_Migrated_Doc', 'dbo')
        print("Documents not Migrated inserted into the 'Not_Migrated_Doc' table.")