import json
import logging
from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import warnings
import pyodbc
import pandas as pd

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

def create_folder(site, library_name, folder_path, name):

    doc_library = site.List(library_name)
    folder_exists = any(item['Name'] == folder_path for item in doc_library.GetListItems())

    if not folder_exists:
        try:
            doc_library.UpdateListItems(data=[
                {
                    'Name': name,
                    'Content Type': 'Folder'
                }
            ], kind='New')
            print(f"Folder '{folder_path}{name}' created successfully.")
        except Exception as e:
            logging.error(f"Error creating folder: {e}")
    else:
        print(f"Folder '{folder_path}' already exists.")

warnings.filterwarnings("ignore")

with open("config.json", "r") as config_file:
    config = json.load(config_file)

sharepoint_config = config["sharepoint_destination_new"]
database_config = config['staging_db']

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
site_url = sharepoint_config["site_url"]
username = sharepoint_config["username"]
password = sharepoint_config["password"]
auth = HttpNtlmAuth(username, password)
site = Site(site_url, auth=auth, verify_ssl=False)

all_list_keys = Get_Documents("SELECT DISTINCT [List Key (List ID)] \
                                FROM Mstr_ListKeys")

for xpcode in all_list_keys:

    library_name = "SPM General Services"
    folder_path = "SPM General Services/"
    folder_name = f"{xpcode}"
    create_folder(site, library_name, folder_path, folder_name)