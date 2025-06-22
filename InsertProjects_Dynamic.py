from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import pandas as pd
import pyodbc
import Get_SPID as spid
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
    df = _query_data(f"SELECT * \
                        FROM PROJECT.PROJECTS_Final")
    df.columns = df.columns.str.lower()
    _col_names = []
    for cname in df.columns:
        if not df[cname].isnull().all():
            _col_names.append(cname.lower())

    source_df = pd.DataFrame({"Source_Column": _col_names})
    mapping_df = _query_data(f"SELECT DISTINCT REPLACE(_Internal_Name, ' ', '') AS [Internal Name], [Display Name1] AS [Internal Name1] \
                                FROM Mapping.Unified_Mapping \
                                WHERE  Destination = 'Projects' \
                                AND [Display Name1] IS NOT NULL \
                                AND [Internal Name] IS NOT NULL \
                                ORDER BY [Internal Name]")
    
    mapping_df['Internal Name'] = mapping_df['Internal Name'].str.lower()

    merged_df = pd.merge(source_df, mapping_df, left_on='Source_Column', right_on='Internal Name', how='left')

    merged_df['Destination_mapping'] = merged_df['Internal Name1']

    merged_df.drop(['Internal Name', 'Internal Name1'], axis=1, inplace=True)

    merged_df['Destination_mapping'].fillna('', inplace=True)

    merged_df = merged_df[merged_df['Destination_mapping'] != '']

    site_url = sharepoint_config['site_url']
    username = sharepoint_config['username']
    password = sharepoint_config['password']

    auth = HttpNtlmAuth(username, password)
    site = Site(site_url, auth=auth, verify_ssl=False)

    list_name = _dest
    sp_list = site.List(list_name)

    _df_errors = pd.DataFrame(columns=['_Error', '_List', '_Type'])
    #merged_df.columns = merged_df.columns.str.lower()
    df_map = merged_df
    print(merged_df)
    print(df)
    #print(df_map)
    
    for index, row in df.iterrows():
        item_data = {}
        for _, mapping_row in df_map.iterrows():
            source_column = mapping_row["Source_Column"]
            destination_column = mapping_row["Destination_mapping"]

            if pd.notnull(row[source_column]):
                item_data[destination_column] = str(row[source_column])
        try:
            if item_data:
                response = sp_list.UpdateListItems(data=[item_data], kind="New")
                #if response['StatusCode'] == 201:
                if response['1,New'] == '0x00000000':
                    print(f"Data uploaded successfully for {_dest} >>{index}<<")
                    print(f"Response Details: {response}")
                else:
                    print(f"Data upload failed for {_dest}. Status: {response}")
                    _df_errors = _df_errors._append({'_Error': str(response), '_List': _dest, '_Type' : 'PDP'}, ignore_index=True)
        except Exception as e:
            print(f"Error occurred for {_dest}>> Column Source [{source_column}]>> Column destination [{destination_column}]: {e}")
            _df_errors = _df_errors._append({'_Error': str(e), '_List': _dest, '_Type' : 'PDP'}, ignore_index=True)
            continue
    df = spid._Get_SPID(site_url, list_name)
    df['PID'] = list_name
    df['Type'] = _dest
    spid.insert_data_into_table(df, "Trace_SPID", "dbo")
    #print(_df_errors)
    spid.insert_x_into_table(_df_errors, "Trace_Errors", "dbo")