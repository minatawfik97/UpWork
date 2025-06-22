from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import Get_SPID as spid
import warnings
import pyodbc
import json

warnings.filterwarnings("ignore")

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

database_config = config['staging_db']
sharepoint_config = config['sharepoint_destination_new']

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

def delete_from_trace_spid(_list):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM [Trace_SPID] WHERE _Type = 'Projects' AND _SPID IN ({','.join(_list)})")
    conn.commit()
    cursor.close()
    conn.close()
    return print("Data Deleted From Trace_SPID Table")

def delete_items_from_sharepoint_list(_dest):
    site_url = sharepoint_config['site_url']
    username = sharepoint_config['username']
    password = sharepoint_config['password']


    auth = HttpNtlmAuth(username, password)
    site = Site(site_url, auth=auth, verify_ssl=False)

    list_name = _dest
    sp_list = site.List(list_name)

    while True:
        df_delete = spid._Get_SPID(site_url, list_name)
        df_delete['PID'] = list_name
        if df_delete.empty:
            print(f"The List {list_name} is Empty")
            break
        else:
            id_list = df_delete['id'].tolist()
            sp_list.UpdateListItems(data=id_list, kind="Delete")
            delete_from_trace_spid(id_list)
            print(f"All Data on list {list_name} Deleted Successfully.. ")

# Call the function to start the process
delete_items_from_sharepoint_list("Projects")