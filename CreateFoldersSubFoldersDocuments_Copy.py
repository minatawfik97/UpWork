import json
import logging
from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import warnings
import pyodbc
import functools

@functools.lru_cache(maxsize=None)
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
old_site_config = config['documents']
doc_config = config['staging_directory']

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
old_site = old_site_config["site"]

doc_sites = Get_Documents("SELECT TABLE_NAME \
                            FROM INFORMATION_SCHEMA.TABLES \
                            WHERE TABLE_SCHEMA = 'DOC_PSLvl' \
                            AND TABLE_NAME = 'Documents'")

all_pcode = Get_Documents("SELECT DISTINCT title \
                            FROM Project.PROJECTS")

all_list_keys = Get_Documents("SELECT DISTINCT [List Key (List ID)] \
                                FROM Mstr_ListKeys")

for xpcode in all_pcode:

    library_name = "Projects Documents"
    folder_path = "Projects Documents/"
    folder_name = f"{xpcode}"
    create_folder(site, library_name, folder_path, folder_name)

    for list_key in all_list_keys:

        folder_name = f"{xpcode}/{list_key}"
        create_folder(site, library_name, folder_path, folder_name)