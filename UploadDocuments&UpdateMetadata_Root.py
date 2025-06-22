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
source_site_config = config['documents']
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
soruce_site = source_site_config["site"]

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

def upload_file(site, auth, target_folder_path, file_name, file_content, msr_path, _id, _createby, _editby, _createdate, _editdate, _lib, _url):
    try:
        request_digest = get_request_digest(site.site_url, auth)

        upload_url = f"{site.site_url}/_api/web/getfolderbyserverrelativeurl(@tfp)/files/add(url='{file_name}', overwrite=true)?@tfp='{target_folder_path}'"
        
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
            doc_library = site.List(_lib)
            doc_library.UpdateListItems(data=[
                {
                    'ID': max_id,
                    'MasarPath': msr_path,
                    'MSR1_PWAListId' : _id,
                    'MSR1_CreatedBy' : _createby,
                    'MSR1_ModifiedBy' : _editby,
                    'MSR1_CreatedDate' : _createdate,
                    'MSR1_ModifiedDate' : _editdate
                }
            ], kind='Update')

            print(f"Metadata for '{file_name}' updated successfully.")
        elif response.status_code == 400:
            print(f"Error: File '{file_name}' already exists in the target folder.")
            print(response.content.decode('utf-8'))
        else:
            print(f"Error uploading file. Status code: {response.status_code}")
            print(response.content.decode('utf-8'))

    except Exception as e:
        logging.error(f"Error uploading file: {e}")

    return response, max_id

doc_sites = ['Documents']

tracing_attachments = pd.DataFrame(columns=['_pcode', '_spid', '_Entity', '_Type', '_Response'])

for _table in doc_sites:

    attachmets = _query_data(f"SELECT serverrelativeurl \
                                ,	LEFT(REPLACE(SUBSTRING(serverrelativeurl, 1, CHARINDEX(name, serverrelativeurl) - 1), \
                                    '/VRO/Documents/', ''), LEN(REPLACE(SUBSTRING(serverrelativeurl, 1, CHARINDEX(name, serverrelativeurl) - 1), \
                                    '/VRO/Documents/', '')) - CHARINDEX('/', REVERSE(REPLACE(SUBSTRING(serverrelativeurl, 1, CHARINDEX(name, serverrelativeurl) - 1), '/VRO/Documents/', '')))) AS Dest \
                                ,	[name] \
                                ,	IIF(ROW_NUMBER() OVER (PARTITION BY [NAME] ORDER BY serverrelativeurl) > 1, CONCAT(id, '_', [name]), [name]) AS sec_name \
                                ,	author \
                                ,	editor \
                                ,	Created \
                                ,	Modified \
                                ,	id \
                            FROM Transformed_RTAttachments \
                             WHERE [name] = 'نموذج توقيع طلب الصلاحية (002).pdf'")

    for index, row in attachmets.iterrows():
        #Files
        partition = doc_config['partition']
        folder = doc_config['Folder']
        path = f"{partition}{folder}RT_Documents\\{row['sec_name']}"

        with open(path, "rb") as file_stream:
            file_content = file_stream.read()
        file_name = file_name = row['name']
        file_name = file_name.replace("'", "")

        _lib = "Masar1Documents"
        folder_path = f"{_lib}/" 
        folder_name = f"{row['Dest']}"
        x = urllib.parse.quote(folder_name)
        print(folder_name)
        target_folder_path = urllib.parse.quote(f"{folder_path}{x}")
        #Metadata
        #spid, pcode, title, msr_path
        _id = row['id']
        _createby = row['author']
        _editby = row['editor']
        _createdate = row['Created']
        _editdate = row['Modified']
        _msr_path = f"{soruce_site}{row['serverrelativeurl']}"
        _url = f"/VRO/{folder_path}{folder_name}/{file_name}"
        encoded_url = urllib.parse.quote(_url.replace("'", "%27"))
        try:
            response, max_id  = upload_file(site, auth, target_folder_path, file_name, file_content, _msr_path, _id, _createby, _editby, _createdate, _editdate, _lib, encoded_url)
             
            data_to_append = {
            '_pcode': folder_name + '/' + file_name,
            '_spid': max_id,
            '_Entity': _lib,
            '_Type' : "Root Document attatchments",
            '_Response' : str(response)
            }

            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)

            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")

        except Exception as e:
            data_to_append = {
            '_pcode': folder_name + '/' + file_name,
            '_spid': 'NotAccessed',
            '_Entity': _lib,
            '_Type' : "Root Document attatchments",
            '_Response' : str(e)
                }
            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)
            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")
            continue