import os
import json
import logging
import requests
from shareplum import Site
from requests_ntlm import HttpNtlmAuth
import warnings
import urllib.parse
import pyodbc
import pandas as pd
import xml.etree.ElementTree as ET
import Get_SPID as spid

warnings.filterwarnings("ignore")

with open("config.json", "r") as config_file:
    config = json.load(config_file)

sharepoint_config = config["sharepoint_destination_new"]
database_config = config['staging_db']
old_site_config = config['documents']
doc_config = config['staging_directory']

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

site_url = sharepoint_config["site_url"]
username = sharepoint_config["username"]
password = sharepoint_config["password"]
auth = HttpNtlmAuth(username, password)
site = Site(site_url, auth=auth, verify_ssl=False)
old_site = old_site_config["site"]

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
    cursor.execute(_query)
    results = cursor.fetchall()
    docs_url = [row[0] for row in results]
    cursor.close()
    _conn.close()
    return docs_url

def pull_data_from_sharepoint(sub_site, url):
    #_service_document_location = f"{sub_site}/_api/web/lists/getbytitle('{list_name}')/items?$orderby=ID desc&$top=1"
    _service_document_location = f"{sub_site}/_api/web/GetFileByServerRelativeUrl(@url)/ListItemAllFields?@url='{url}'"
    response = requests.get(_service_document_location, auth=HttpNtlmAuth(username, password), verify=False)
    if response.status_code == 200:
        xml_string = response.content
    else:
        print("Error")

    data = []

    root = ET.fromstring(xml_string)

    for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
        entry_data = {}
        for elem in entry.iter():
            if elem.tag.startswith('{http://schemas.microsoft.com/ado/2007/08/dataservices}') or elem.tag.endswith('title'):
                value = elem.text                
                entry_data[elem.tag.split('}')[1].lower()] = value  # Change column name to lowercase
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
    else:
        df = pd.DataFrame()
    return df

def insert_data_into_table(df, table_name, _schema):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(df.columns))
    insert_sql = f"INSERT INTO [{_schema}].[{table_name}] (_Title, _SPID, _Entity, _Type, _Response) VALUES ({placeholders})"

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

def upload_file(site, auth, target_folder_path, file_name, file_content, title, msr_path, _url):
    try:
        request_digest = get_request_digest(site.site_url, auth)

        target_folder_url = f"{site.site_url}/{target_folder_path}"

        file_exists_url = f"{target_folder_url}/{urllib.parse.quote(file_name)}"
        file_exists_response = requests.get(file_exists_url, auth=auth, headers={'accept': 'application/json;odata=verbose'}, verify=False)

        if file_exists_response.status_code == 200:
            print(f"File '{file_name}' already exists in the target folder. Skipping upload.")
            return
        elif file_exists_response.status_code != 404:
            print(f"Error checking file : {file_exists_response.status_code}")
            print(file_exists_response.content.decode('utf-8'))
            return

        # Continue with the file upload
        upload_url = f"{site.site_url}/_api/web/getfolderbyserverrelativeurl('{urllib.parse.quote(target_folder_path)}')/files/add(url='{file_name}', overwrite=true)"

        response = requests.post(upload_url,
                                 auth=auth,
                                 headers={'accept': 'application/json;odata=verbose',
                                          'X-RequestDigest': request_digest},
                                 data=file_content,
                                 verify=False)

        if response.status_code == 200:
            print(f"File '{file_name}' uploaded successfully.")

            df_max_spid = pull_data_from_sharepoint(site_url, _url)
            max_id = df_max_spid['id'].max()
            print(f"Max ID IS: {max_id}")
            doc_library = site.List("SPM General Services")
            doc_library.UpdateListItems(data=[
                {
                    'ID': max_id,
                    'MasarPath': msr_path,
                    'Title': title
                }
            ], kind='Update')

            print(f"Metadata for '{file_name}' updated successfully.")

        else:
            print(f"Error uploading file. Status code: {response.status_code}")
            #print(response.content.decode('utf-8'))

    except Exception as e:
        logging.error(f"Error uploading file: {e}")

    return response, max_id

doc_sites = ['DOC_RTLvl']

tracing_attachments = pd.DataFrame(columns=['_pcode', '_spid', '_Entity', '_Type', '_Response'])

for _table in doc_sites:

    attachmets = _query_data(f"SELECT DISTINCT \
                                T1.[filename] \
                            ,	T1.serverrelativeurl \
                            ,	ISNULL(T1.PCODE, 'NoProject') PCODE \
                            ,	T1.Main_Folder \
                            ,	T1.Sub_Folder \
                            ,	T1._SPID \
                            ,	T1.Title \
                            ,   CONCAT(SUBSTRING(serverrelativeurl, CHARINDEX('/Attachments/', serverrelativeurl) + LEN('/Attachments/'), \
								CHARINDEX('/', serverrelativeurl, CHARINDEX('/Attachments/', serverrelativeurl) + LEN('/Attachments/')) \
                                    - (CHARINDEX('/Attachments/', serverrelativeurl) + LEN('/Attachments/'))), \
								'_', [filename]) _filename \
                        FROM {_table}.[List_Attachments] T1 \
                        WHERE T1.Main_Folder IS NULL")

    for index, row in attachmets.iterrows():
        #Files
        partition = doc_config['partition']
        folder = doc_config['Folder']
        path = f"{partition}{folder}{_table}_List_Attachments\\{row['PCODE']}\\{row['_filename']}"

        with open(path, "rb") as file_stream:
            file_content = file_stream.read()
        file_name = file_name = row['_filename']
        file_name = file_name.replace("'", "")

        folder_path = "SPM General Services/"
        folder_name = f"{row['Sub_Folder']}"
        target_folder_path = f"{folder_path}{folder_name}"
        #Metadata
        #spid, pcode, title, msr_path
        _title = row['Title']
        _msr_path = f"{old_site}{row['serverrelativeurl']}"
        _url = f"/VRO/{folder_path}{folder_name}/{file_name}"
        encoded_url = urllib.parse.quote(_url.replace("'", "%27"))
        try:
            response, max_id = upload_file(site, auth, target_folder_path, file_name, file_content, _title, _msr_path, encoded_url)

            data_to_append = {
            '_pcode': str(folder_name + '/' + file_name),
            '_spid': max_id,
            '_Entity': "SPM General Services",
            '_Type' : "List attatchments",
            '_Response' : str(response)
            }

            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)

            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")

        except Exception as e:
            data_to_append = {
            '_pcode': str(folder_name + '/' + file_name),
            '_spid': 'NotAccessed',
            '_Entity': "SPM General Services",
            '_Type' : "List attatchments",
            '_Response' : str(e)
                }
            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)
            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")
            continue