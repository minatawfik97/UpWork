from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import warnings
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
conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};\
            SERVER={_server};\
            DATABASE={_database};\
            UID={_user};\
            PWD={_pw};\
            CHARSET=utf8;COLLATION=Arabic_CI_AI'

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

def Get_Lookup_Name_Table():
    _conn = pyodbc.connect(conn_str)
    cursor = _conn.cursor()
    _query = f"SELECT DISTINCT '[PROJECT].[PROJECTS]' AS [Name], \
                    'Mapping.Unified_Mapping' AS Table_Name, Destination \
                    FROM Mapping.Unified_Mapping \
                    WHERE Destination = 'Projects'"
    cursor.execute(_query)
    results = cursor.fetchall()
    dict_lookup = {}
    for row in results:
        dict_lookup[row[0]] = (row[1], row[2])
    cursor.close()
    _conn.close()
    return dict_lookup

_dict_lookup = Get_Lookup_Name_Table()

for _name, (_table, _dest) in _dict_lookup.items():
    query = "SELECT T2._SPID, T1._SPID AS MID \
                FROM GoLive.Benefits_PDP T1 \
                INNER JOIN Trace_SPID T2 \
                ON T1._code = T2._Title"
    query_result = _query_data(query)

    # SharePoint setup
    site_url = sharepoint_config['site_url']
    username = sharepoint_config['username']
    password = sharepoint_config['password']
    auth = HttpNtlmAuth(username, password)
    site = Site(site_url, auth=auth, verify_ssl=False)
    list_name = _dest
    sp_list = site.List(list_name)

    # Iterate through the query result DataFrame
    for index, row in query_result.iterrows():
        try:
            # Extract the relevant values from the DataFrame
            item_id = row['_SPID']
            pid = row['MID']

            if pd.notnull(item_id) and pd.notnull(pid):
                # Define the item_data dictionary with the values to update
                item_data = {
                    'ID': item_id,
                    'MasterID': pid,
                }

                # Use doc_library.UpdateListItems to update the specific columns
                response = sp_list.UpdateListItems(data=[item_data], kind='Update')

                if response['1,Update'] == '0x00000000':
                    print(f"Data updated successfully for {_dest} with ID {item_id}")
                    print(f"Response Details: {response}")
                else:
                    print(f"Data update failed for {_dest} with ID {item_id}. Status: {response}")
        except Exception as e:
            print(f"Error occurred for {_dest} with ID {item_id}: {e}")