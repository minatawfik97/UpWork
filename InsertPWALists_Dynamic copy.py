from requests_ntlm import HttpNtlmAuth
import requests
import logging
import pandas as pd
import pyodbc
import Get_SPID as spid
import json
import warnings

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
    _query = f"SELECT DISTINCT REPLACE(_Source, ' ' , '') AS _Source, \
                        'Mapping.Unified_Mapping' AS Table_Name, Destination, \
                        CASE WHEN _Source = 'ChangeRequest2020' THEN 2 ELSE 1 END AS _RN \
                FROM Mapping.Unified_Mapping \
                WHERE Table_Type = 'PWA List' \
                    AND Destination <> 'Project Stages' \
                    AND _Source IN ('CAB Requests') \
                ORDER BY _Source, _RN"
    cursor.execute(_query)
    results = cursor.fetchall()
    dict_lookup = {}
    for row in results:
        dict_lookup[row[0]] = (row[1], row[2])
    cursor.close()
    _conn.close()
    return dict_lookup

_dict_lookup = Get_Lookup_Name_Table()

def get_request_digest(site_url, auth):
        try:
            request_digest_url = f"{site_url}/_api/contextinfo"
            response = requests.post(request_digest_url,
                                    headers={'accept': 'application/json;odata=verbose'},
                                    auth=auth, verify=False)
            response.raise_for_status()
            return response.json()['d']['GetContextWebInformation']['FormDigestValue']
        except requests.exceptions.RequestException as e:
            logging.error(f"Error getting request digest: {e}")
            return None

def _ingest_data(_item_data, _list_name):
        endpoint_url = f"{site_url}/_api/Web/Lists/GetByTitle('{_list_name}')/Items"

        request_digest = get_request_digest(site_url, auth)

        headers = {
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "odata": "verbose",
            "X-RequestDigest": request_digest
        }
        _item_data = {"__metadata": {"type": "SP.ListItem"}, **_item_data}

        response = requests.post(url=endpoint_url, json=_item_data, headers=headers, auth=auth, verify=False)

        return response

for _Source_name, (_table, _dest) in _dict_lookup.items():
    df = _query_data(f"SELECT * FROM GoLive.[{_Source_name}]")
    df.columns = df.columns.str.lower()
    _col_names = []
    for cname in df.columns:
        if not df[cname].isnull().all():
            _col_names.append(cname.lower())

    source_df = pd.DataFrame({"Source_Column": _col_names})
    mapping_df = _query_data(f"SELECT DISTINCT REPLACE([Internal Name], ' ', '') AS [Internal Name], \
                                        [Internal Name1] AS [Internal Name1] \
                                FROM {_table} \
                                WHERE [Internal Name] IN ('editorid') \
                                        AND [Display Name1] <> 'NULL' \
                                        AND Table_Type = 'PWA List' \
                                        AND REPLACE(_Source, ' ', '') = '{_Source_name}' \
                                        AND Destination = '{_dest}' \
                                        AND REPLACE(_Source, ' ', '') NOT IN ('KPIs') \
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
    print(_dest)
    list_name = _dest

    df_map = merged_df

    print(merged_df)
    # print(df)
    _df_errors = pd.DataFrame(columns=['_Error', '_List', '_Type'])
    
    for index, row in df.iterrows():
        item_data = {}
        for _, mapping_row in df_map.iterrows():
            source_column = mapping_row["Source_Column"]
            destination_column = mapping_row["Destination_mapping"]

            if pd.notnull(row[source_column]):
                item_data[destination_column] = str(row[source_column])           
        try:    
            if item_data:
                print(item_data)
                response = _ingest_data(_item_data=item_data, _list_name=list_name)

                if response.status_code == 201:
                    print(f"Data uploaded successfully for {_dest} >>{index+1}<<")
                else:
                        print(f"Data upload failed for {_dest}>> {source_column}>> {destination_column} : {response.content.decode('utf-8')} ")
                        _df_errors = _df_errors._append({'_Error': str(response), '_List': _dest, '_Type' : 'PWA'}, ignore_index=True)
                        break
        except Exception as e:
            print(f"Error occurred for {_dest}>> Column Source [{source_column}]>> Column destination [{destination_column}]: {e}")
            _df_errors = _df_errors._append({'_Error': str(e), '_List': _dest, '_Type' : 'PWA'}, ignore_index=True)
            continue
    df = spid._Get_SPID(site_url, list_name)
    df['PID'] = list_name
    df['Type'] = 'PWA List'
    spid.insert_data_into_table(df, "Trace_SPID", "dbo")

    spid.insert_x_into_table(_df_errors, "Trace_Errors", "dbo")