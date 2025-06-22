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

def Get_Lookup_Name_Table():
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
    _query = f"SELECT DISTINCT REPLACE(_Source, ' ' , '') AS _Source, \
                        'Mapping.Unified_Mapping' AS Table_Name, Destination \
                FROM Mapping.Unified_Mapping \
                WHERE Table_Type = 'Project List'"
    cursor.execute(_query)
    results = cursor.fetchall()
    dict_lookup = {}
    for row in results:
        dict_lookup[row[0]] = (row[1], row[2])
    cursor.close()
    _conn.close()
    return dict_lookup

_dict_lookup = Get_Lookup_Name_Table()

def delete_from_trace_spid(_list):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM [Trace_SPID] WHERE _Type = 'Project List' AND _SPID IN ({','.join(_list)})")
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

for _Source_name, (_table, _dest) in _dict_lookup.items():
    delete_items_from_sharepoint_list(f"{_dest}")