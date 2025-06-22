import requests
import xml.etree.ElementTree as ET
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import json
import warnings
import os
warnings.filterwarnings("ignore")

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

database_config = config['staging_db']
sharepoint_config = config['sharepoint_source_projectserver']
staging_dir = config['staging_directory']

#Stading Dir
_partition_name = staging_dir["partition"]
_folder = staging_dir["Folder"]

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
_list = "Projects"
_username = sharepoint_config['username']
_password = sharepoint_config['password']
_base_url = sharepoint_config['site_url']
_skip = 0
_top = 300
_max_records = 20000

def _pull_data_from_sharepoint(skip, top):
    url = f"{_base_url}?$skip={skip}&$top={top}"
    response = requests.get(url, auth=HttpNtlmAuth(_username, _password), verify=False)
    if response.status_code == 200:
        xml_string = response.content.decode('utf-8').replace('&', '')
    else:
        print("Error receiving XML data")

    data = []
    try:
        root = ET.fromstring(xml_string)
        for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
            entry_data = {}
            for elem in entry.iter():
                if elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or elem.tag.endswith(
                        'title'):
                    value = elem.text
                    entry_data[elem.tag.split('}')[1]] = value
            data.append(entry_data)
    except ET.ParseError as error:
        print(f"Error parsing XML: {str(error)}")

    df = pd.DataFrame(data)

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
            if value == 'NULL':
                processed_row.append(None)  # Replace 'NULL' with None
            elif isinstance(value, float) and pd.isnull(value):
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

# Loop and save data to CSV and insert into SQL
last_csv_empty = False
combined_df = pd.DataFrame()

while _skip < _max_records:
    df = _pull_data_from_sharepoint(_skip, _top)

    if df.empty:
        last_csv_empty = True
        break
    else:
        print(f"CSV data{_skip}.csv created successfully")
        print(df.head())

        table_name = f"Projects_0"
        combined_df = combined_df._append(df)

        _skip += _top

create_table_from_csv(combined_df, table_name, 'dbo')
insert_data_into_table(combined_df, table_name, 'dbo')