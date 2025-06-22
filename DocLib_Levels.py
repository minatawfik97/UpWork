import pandas as pd
import pyodbc
import warnings
import json

warnings.filterwarnings('ignore')

with open("config.json", "r") as config_file:
    config = json.load(config_file)

database_config = config['staging_db']

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

def table_exists(cursor, table_name, _schema):
    cursor.execute(f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES \
                        WHERE TABLE_NAME = '{table_name}' \
                        AND TABLE_SCHEMA = '{_schema}'")
    return cursor.fetchone()[0] != 0

def create_table_from_df(df, table_name, _schema):
    #df = pd.read_csv(csv_file)
    df.columns = df.columns.str.lower()  # Change column names to lowercase
    df = df.loc[:, ~df.columns.duplicated()]

    column_names = df.columns.tolist()
    column_types = df.dtypes.tolist()

    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    if table_exists(cursor, table_name, _schema):
        cursor.execute(f"DROP TABLE [{_schema}].[{table_name}]")

    create_table_query = f"CREATE TABLE [{_schema}].[{table_name}] ("
    for column_name, column_type in zip(column_names, column_types):
        if column_type == 'int64':
            sql_type = 'NVARCHAR(MAX)'
        elif column_type == 'float64':
            sql_type = 'NVARCHAR(MAX)'
        else:
            sql_type = 'NVARCHAR(MAX)'
        create_table_query += f"[{column_name}] {sql_type}, "
    create_table_query = create_table_query.rstrip(', ') + ");"

    cursor.execute(create_table_query)
    conn.commit()

    cursor.close()
    conn.close()
    print(f"Table '{_schema}'.'{table_name}' created successfully")

def insert_data_into_table(df, table_name, _schema):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(df.columns))
    insert_sql = f"INSERT INTO [{_schema}].[{table_name}] VALUES ({placeholders})"

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


    
all_projects = _query_data(f"SELECT DISTINCT serverrelativeurl, REPLACE(REPLACE(serverrelativeurl, NAME, ''), '/VRO/Documents/', '') AS PATH \
                            FROM DOC_RTLvl.Documents T1")
def extract_levels(path):
    levels = path.split('/')
    for i, level in enumerate(levels):
        yield path, level, i + 1

extracted_data = []

for path in all_projects['PATH']:
    extracted_data.extend(extract_levels(path))

result_df = pd.DataFrame(extracted_data, columns=['File_Path', 'Level_Name', 'Level_Number'])

print(result_df)

create_table_from_df(result_df, "Documents_levels", 'DOC_RTLvl')
insert_data_into_table(result_df, "Documents_levels", 'DOC_RTLvl')