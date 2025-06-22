import json
import logging
from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import warnings
import pyodbc
import functools
import multiprocessing

@functools.lru_cache(maxsize=None)
def Get_Documents(_query):
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
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

def create_main_folders(main_folders):
    library_name = "Projects Documents"
    
    for main_folder in main_folders:
        folder_path = "Projects Documents/"
        folder_name = f"{main_folder}"
        create_folder(site, library_name, folder_path, folder_name)

def create_subfolders(main_folder, list_keys):
    library_name = "Projects Documents"
    folder_path = f"Projects Documents/{main_folder}"
    
    for sub_folder in list_keys:
        folder_name = f"{main_folder}/{sub_folder}"
        create_folder(site, library_name, folder_path, folder_name)

warnings.filterwarnings("ignore")

with open("config.json", "r") as config_file:
    config = json.load(config_file)

sharepoint_config = config["sharepoint_destination_old"]
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

all_pcode = Get_Documents("SELECT DISTINCT title \
                            FROM Project.Projects_Final")

all_list_keys = ["Projects"]


if __name__ == "__main__":

    chunk_size = 50

    for start in range(0, len(all_pcode), chunk_size):
        _chunk = all_pcode[start:start + chunk_size]
        #print(_chunk)

        chunks = 50
        main_folder_chunks = [_chunk[i:i + chunks] for i in range(0, len(_chunk), chunks)]
        processes = []

        for main_folders in main_folder_chunks:
            p_main = multiprocessing.Process(target=create_main_folders, args=(main_folders,))
            p_main.start()
            processes.append(p_main)

        for p_main in processes:
            p_main.join()

        processes = []

        for main_folder in _chunk:
            p_sub = multiprocessing.Process(target=create_subfolders, args=(main_folder, all_list_keys))
            p_sub.start()
            processes.append(p_sub)

        for p_sub in processes:
            p_sub.join()