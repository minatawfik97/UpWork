import requests
import xml.etree.ElementTree as ET
from requests_ntlm import HttpNtlmAuth
import pyodbc
import pandas as pd
import json

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

database_config = config['staging_db']
sharepoint_config = config['sharepoint_destination_new']

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

#SharePoint
site_url = sharepoint_config['site_url']
username = sharepoint_config['username']
password = sharepoint_config['password']


def _Get_SPID(_Site, _list_name):
    _service_document_location = f"{_Site}/_api/web/lists/getbytitle('{_list_name}')/items"
    data = []

    while _service_document_location:
        response = requests.get(_service_document_location, auth=HttpNtlmAuth(username, password), verify=False)
        if response.status_code == 200:
            xml_string = response.content
        else:
            print("Error")
            return pd.DataFrame()  

        root = ET.fromstring(xml_string)

        for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
            entry_data = {}
            for elem in entry.iter():
                if elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or elem.tag.endswith('title'):
                    value = elem.text
                    entry_data[elem.tag.split('}')[1].lower()] = value  
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
        _dff = df[['title', 'id']]
    else:
        _dff = pd.DataFrame()
    return _dff


def _Get_SPID_Desc(_Site, _list_name):
    _service_document_location = f"{_Site}/_api/web/lists/getbytitle('{_list_name}')/items?$orderby=ID desc&$top=1"
    data = []

    while _service_document_location:
        response = requests.get(_service_document_location, auth=HttpNtlmAuth(username, password), verify=False)
        if response.status_code == 200:
            xml_string = response.content
        else:
            print("Error")
            return pd.DataFrame()  

        root = ET.fromstring(xml_string)

        for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
            entry_data = {}
            for elem in entry.iter():
                if elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or elem.tag.endswith('title'):
                    value = elem.text
                    entry_data[elem.tag.split('}')[1].lower()] = value  
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
        _dff = df[['title', 'id']]
    else:
        _dff = pd.DataFrame()
    return _dff

def insert_data_into_table(df, table_name, _schema):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(df.columns))
    insert_sql = f"INSERT INTO [{_schema}].[{table_name}] (_Title, _SPID, _Entity, _Type) VALUES ({placeholders})"

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

def insert_x_into_table(df, table_name, _schema):
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