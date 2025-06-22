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
from requests_toolbelt.multipart.encoder import MultipartEncoder

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


def upload_file(site, auth, target_folder_path, file_name, file_content, spid, pcode, title, msr_path, _RelatedPhase, _id, _createby, _editby, _createdate, _editdate, _lib, _url):
    try:
        request_digest = get_request_digest(site.site_url, auth)

        upload_url = f"{site.site_url}/_api/web/getfolderbyserverrelativeurl('{urllib.parse.quote(target_folder_path)}')/files/add(url='{file_name}', overwrite=true)"

        chunk_size = 1 * 1024 * 1024
        total_chunks = (len(file_content) + chunk_size - 1) // chunk_size

        # Initialize MultipartEncoder fields
        fields = {}

        # Upload each chunk
        for i in range(total_chunks):
            start_byte = i * chunk_size
            end_byte = min((i + 1) * chunk_size, len(file_content))
            chunk_data = file_content[start_byte:end_byte]

            # Initialize MultipartEncoder with current chunk data
            encoder = MultipartEncoder(fields={'file': (file_name, chunk_data)})

            headers = {
                'accept': 'application/json;odata=verbose',
                'X-RequestDigest': request_digest,
                'Content-Type': encoder.content_type,
                'Content-Length': str(len(chunk_data)),
                'Content-Range': f'bytes {start_byte}-{end_byte - 1}/{len(file_content)}'
            }

            response = requests.post(upload_url,
                                     auth=auth,
                                     headers=headers,
                                     data=encoder,
                                     verify=False)

            # Check if the response is successful
            if response.status_code != 200:
                raise Exception(f"Error uploading chunk {i + 1} of '{file_name}'. Status code: {response.status_code}")

            # Update MultipartEncoder fields for the next chunk
            fields.update({'file': (file_name, chunk_data)})

        # If all chunks uploaded successfully, update metadata
        print(f"All chunks of '{file_name}' uploaded successfully.")
        
        df_max_spid = pull_data_from_sharepoint(site_url, _url)
        max_id = df_max_spid['id'].max()
        print(f"Max ID IS: {max_id}")
        doc_library = site.List(_lib)
        doc_library.UpdateListItems(data=[
            {
                'ID': max_id,
                'ItemID': spid,
                'ProjectCode': pcode,
                'MasarPath': msr_path,
                'Title': title,
                'RelatedPhase' : _RelatedPhase,
                'MSR1_ListId' : _id,
                'MSR1_CreatedBy' : _createby,
                'MSR1_ModifiedBy' : _editby,
                'MSR1_CreatedDate' : _createdate,
                'MSR1_ModifiedDate' : _editdate
            }
        ], kind='Update')

        print(f"Metadata for '{file_name}' updated successfully.")

    except Exception as e:
        print(f"Error uploading file '{file_name}': {e}")

    return response, max_id

doc_sites = ['Documents', 'ضبط الوثائق']

tracing_attachments = pd.DataFrame(columns=['_pcode', '_spid', '_Entity', '_Type', '_Response'])

for _table in doc_sites:

    attachmets = _query_data(f"SELECT DISTINCT \
                        T1.[name] \
                    ,   T1.pid \
                    ,	T1.serverrelativeurl \
                    ,	T2.title AS PCODE \
                    ,	T2.title As Main_Folder \
                    ,	'projects' AS Sub_Folder \
                    ,   T4._filename \
                    ,	T4.RelatedPhase \
                    ,	T3._SPID \
                    ,	T4.id \
					,	T4.author \
					,	T4.editor \
					,	T4.Created \
					,	T4.Modified \
                    ,   CASE WHEN _Doc = 'Documents' Then 'Projects Documents' ELSE 'Projects Confidential Documents' END AS Destination \
                    ,	CONCAT('projects-', T2.title, ';projects;proposalreport;projectmanagementplan;ownerbusinessrequirements;organizationhealth;coc;cocitem;projectcharter;benefitevaluation;evaluationreport;projectevaluationreport;closureformreport') AS Title \
                FROM DOC_PSLvl.[{_table}] T1 \
                LEFT JOIN Project.Projects_Final T2 \
                    ON T1.pid = T2.pid \
                LEFT JOIN Trace_SPID T3 \
                    ON T2.title = T3._Title \
                INNER JOIN [dbo].[Transformed_ProjectAttachments] T4 \
                    ON T1.pid = T4.pid AND T1.serverrelativeurl = T4.serverrelativeurl \
		        INNER JOIN Trace_SPID_Attachments_failed T6 \
		            ON CONCAT(T2.title, '/', 'projects', '/', REPLACE([_filename], '''', '')) = T6._Title \
                    AND CASE WHEN _Doc = 'Documents' Then 'Projects Documents' ELSE 'Projects Confidential Documents' END = T6._Entity \
		        WHERE T6._Response <> '<Response [200]>' AND T6._Type IN ('Document attatchments', 'Projects Confidential Document') \
                AND T4._filename = 'وثيقة إدارة المشروع (1).rar'")

    for index, row in attachmets.iterrows():
        #Files
        partition = doc_config['partition']
        folder = doc_config['Folder']
        path = f"{partition}{folder}{_table}\\{str(row['pid'])}\\{row['_filename']}"

        with open(path, "rb") as file_stream:
            file_content = file_stream.read()
        file_name = file_name = row['_filename']
        file_name = file_name.replace("'", "")

        folder_path = f"{row['Destination']}/" 
        folder_name = f"{row['Main_Folder']}/{row['Sub_Folder']}"
        target_folder_path = urllib.parse.quote(f"{folder_path}{folder_name}")
        #Metadata
        #spid, pcode, title, msr_path
        _spid = row['_SPID']
        _pcode = row['PCODE']
        _title = row['Title']
        _id = row['id']
        _createby = row['author']
        _editby = row['editor']
        _createdate = row['Created']
        _editdate = row['Modified']
        _msr_path = f"{soruce_site}{row['serverrelativeurl']}"
        _relatedphase = row['RelatedPhase']
        _lib = row['Destination']
        _url = f"/VRO/{row['Destination']}/{folder_name}/{file_name}"
        encoded_url = urllib.parse.quote(_url.replace("'", "%27"))
        try:
            response, max_id  = upload_file(site, auth, target_folder_path, file_name, file_content, _spid, _pcode, _title, _msr_path, _relatedphase, _id, _createby, _editby, _createdate, _editdate, _lib, encoded_url)
             
            data_to_append = {
            '_pcode': folder_name + '/' + file_name,
            '_spid': max_id,
            '_Entity': f"{row['Destination']}",
            '_Type' : "Document attatchments",
            '_Response' : str(response)
            }

            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)

            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")

        except Exception as e:
            data_to_append = {
            '_pcode': folder_name + '/' + file_name,
            '_spid': 'NotAccessed',
            '_Entity': f"{row['Destination']}",
            '_Type' : "Document attatchments",
            '_Response' : str(e)
                }
            tracing_attachments = tracing_attachments.iloc[0:0]
            tracing_attachments = tracing_attachments._append(data_to_append, ignore_index=True)
            insert_data_into_table(tracing_attachments, "Trace_SPID_Attachments", "dbo")
            continue