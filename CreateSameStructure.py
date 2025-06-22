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

def create_folder(site, library_name, base_path, name):

    doc_library = site.List(library_name)
    try:
        doc_library.UpdateListItems(data=[
            {
                'Name': name,
                'Content Type': 'Folder'
            }
        ], kind='New')
        print(f"Folder '{name}' created successfully. On {base_path}")
    except Exception as e:
        logging.error(f"Error creating folder: {e}")
        
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
_lib = "Masar1Documents"
#Masar1Documents_NoData

_basepath = _query_data("SELECT DISTINCT level_name \
                        FROM DOC_RTLvl._DOC \
                        WHERE level_name <> '' AND level_number = 1")

for index, row in _basepath.iterrows():
    library_name = _lib
    base_path = f"{_lib}/"
    folder_name = f"{row['level_name']}"
    create_folder(site, _lib, base_path, folder_name)

sub_folders = _query_data(f"SELECT DISTINCT file_path, level_name, level_number, Base_url \
                            FROM DOC_RTLvl._DOC \
                            WHERE level_name <> '' AND level_number > 1 \
                            ORDER BY Base_url, level_number")

for index, row in sub_folders.iterrows():
    library_name = _lib
    base_path = f"{_lib}/{row['Base_url']}/"
    folder_name = f"{row['Base_url']}/{row['level_name']}"
    create_folder(site, _lib, base_path, folder_name)