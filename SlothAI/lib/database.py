"""
database.py provides function to interact with FeatureBase cloud. It wraps the
featurebase client library.
"""

import featurebase
from urllib.error import HTTPError, URLError, ContentTooShortError

from flask import current_app as app

###############
# FeatureBase #
###############

def featurebase_query(document, debug=False):
	"""
    Execute a query against FeatureBase cloud and return the response and any query errors.

    Args:
    - document (dict): A dictionary containing the query information.
        - 'sql' (str): The SQL query to be executed.
        - 'dbid' (str): The database ID in FeatureBase cloud.
        - 'db_token' (str): The API key/token for authentication.

    - debug (bool, optional): If True, enables debug mode for additional logging (default is False).

    Returns:
    Tuple:
        - resp (object): The response from the Featurebase query.
        - query_error (str): Any error message from the query execution, or None if there were no errors.
    """
	sql = document.get("sql")
	dbid = document.get('dbid')
	db_token = document.get('db_token')

	fb_client = featurebase.client(
		hostport=app.config['FEATUREBASE_ENDPOINT'],
		database=dbid,
		apikey=db_token
	)

	if debug:
		print(f"dbid: {fb_client.database}")
		print(f"apikey: {fb_client.apikey}")
		print(f"hostport: {fb_client.hostport}")

	try:
		resp = fb_client.query(sql=sql)
		if resp.error:
				if len(sql) > 100:
					partial_query = sql[:100]
				else:
					partial_query = sql				
				return None, f"featurebase_query: {partial_query}... :{resp.error}"
		return resp, None
	except (HTTPError, URLError, ContentTooShortError, Exception)  as err:
		return None, f"featurebase_query: exception: {err.reason}"


def featurebase_querybatch(document, debug=False):
	"""
    Execute a query against FeatureBase cloud and return the response and any query errors.

    Args:
    - document (dict): A dictionary containing the query information.
        - 'sqllist' (str): The SQL query to be executed.
        - 'dbid' (str): The database ID in FeatureBase cloud.
        - 'db_token' (str): The API key/token for authentication.

    - debug (bool, optional): If True, enables debug mode for additional logging (default is False).

    Returns:
    Tuple:
        - resp (object): The response from the Featurebase query.
        - query_error (str): Any error message from the query execution, or None if there were no errors.
    """
	sqllist = document.get("sqllist")
	dbid = document.get('dbid')
	db_token = document.get('db_token')

	fb_client = featurebase.client(
		hostport=app.config['FEATUREBASE_ENDPOINT'],
		database=dbid,
		apikey=db_token
	)

	if debug:
		print(f"dbid: {fb_client.database}")
		print(f"apikey: {fb_client.apikey}")
		print(f"hostport: {fb_client.hostport}")

	try:
		errs = []
		results = fb_client.querybatch(sqllist, asynchronous=True)
		for result in results:
			if result.error:		
				errs.append(f"featurebase_query:{result.error}")
		if len(errs) == 0:
			return results, None
		else:
			return results, errs
	except (HTTPError, URLError, ContentTooShortError)  as err:
		return None, f"featurebase_query: {err.reason}"
	except Exception as e:
		return None, f"featurebase_query: unhandled excpetion while running query: {e}"


def create_table(name, schema, auth):
	"""
    Create a table in Featurebase Cloud with the specified name and schema.

    Args:
    - name (str): The name of the table to be created.
    - schema (str): The schema definition for the table in SQL format.
    - auth (dict): A dictionary containing authentication information.
        - 'dbid' (str): The database ID in Featurebase.
        - 'db_token' (str): The API key/token for authentication.

    Returns:
    str or None: If an error occurs during table creation, it returns an error message. Otherwise, it returns None.
	"""

	_, err = featurebase_query(
		{
			"sql": f"CREATE TABLE {name} {schema};",
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)
		
	return err

def drop_table(name, auth):
	"""
    Drop a table in Featurebase Cloud with the specified name.

    Args:
    - name (str): The name of the table to be dropped.
    - auth (dict): A dictionary containing authentication information.
        - 'dbid' (str): The database ID in Featurebase.
        - 'db_token' (str): The API key/token for authentication.

    Returns:
    str or None: If an error occurs while dropping the table, it returns an error message. Otherwise, it returns None.
	"""

	_, err = featurebase_query(
		{
			"sql": f"DROP TABLE {name};",
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)

	if err:
		print(f"Error dropping table {name} on FeatureBase Cloud: {err}")
	else:
		print(f"Successfully dropped table `{name}` on FeatureBase Cloud.")
		
	return err
	
def table_exists(name, auth):
	"""
    Check if a table with the given name exists in a database using a featurebase_query.

    Parameters:
    - name (str): The name of the table to check for existence.
    - auth (dict): A dictionary containing authentication information for the featurebase_query.

    Returns:
    - bool or None: If the table exists, returns True. If the table does not exist or an error occurs,
      returns False. If there's an error in the featurebase_query operation, returns None.
	"""

	resp, err = featurebase_query(
		{
			"sql": f"SHOW TABLES;",
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)
	if err:
		return None, err
	
	for tbl in resp.data:
		if tbl[0] == name:
			return True, None
	
	return False, None

def get_columns(table_name, auth):
	"""
    Retrieve column information for a specified table from a database using Featurebase.

    Args:
        table_name (str): The name of the table for which column information is needed.
        auth (dict): A dictionary containing authentication information for Featurebase, including:
            - 'dbid' (str): The database ID.
            - 'db_token' (str): The database access token.

    Returns:
        dict or None: A dictionary where keys are column names, and values are column data types.
            Returns None if there was an error during the retrieval process.
        
        str or None: An error message if an error occurred during the retrieval process.
            Returns None if the retrieval was successful.
	"""

	resp, err = featurebase_query(
		{
			"sql": f"SHOW COLUMNS FROM {table_name};",
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)
	if err:
		return None, err
	
	columns = {}
	for column in resp.data:
		columns[column[0]] = column[2]
		
	return columns, None

def add_column(table_name, column, auth):
	"""
    Add a new column to a specified table in a database using Featurebase.

    Args:
        table_name (str): The name of the table to which the column will be added.
        column (dict): A dictionary containing information about the column to be added, including:
            - 'name' (str): The name of the new column.
            - 'type' (str): The data type of the new column.
        auth (dict): A dictionary containing authentication information for Featurebase, including:
            - 'dbid' (str): The database ID.
            - 'db_token' (str): The database access token.

    Returns:
        str or None: An error message if an error occurred during the column addition process.
            Returns None if the column was added successfully.
	"""

	_, err = featurebase_query(
		{
			"sql": f"ALTER TABLE {table_name} ADD COLUMN {column['name']} {column['type']}",
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)
		
	return err


def add_filters_to_sql(original_sql_query, column_value_dict):
	"""
	Modify an SQL query to filter records based on column values.

	This function takes an original SQL query and a dictionary of column-value
	pairs. It constructs a new SQL query with a WHERE clause that filters
	records based on the values provided in the column_value_dict. The function
	handles different data types and ensures proper escaping of values for SQL
	queries.

	Args:
	    original_sql_query (str): The original SQL query to be modified.
	    column_value_dict (dict): A dictionary mapping column names to lists of
	    values to filter on.

	Returns:
	    str: The modified SQL query with the added WHERE clause for filtering.
	    str or None: An error message if any validation checks fail, or None if
	    successful.

	Example:
		original_query = "SELECT * FROM my_table WHERE category = 'A'"
		column_values = {
			"column1": [1, 2, 3], "column2": ["X", "Y"],
		} modified_query, error = modify_sql_query(original_query,
		column_values)

		if error:
			print(f"Error: {error}")
		else:
			print(f"Modified Query: {modified_query}") 
			# Modified Query: "SELECT * FROM my_table WHERE column1 IN (1, 2, 3)
			AND column2 IN ('X', 'Y') AND category = 'A'",

	Notes:
		- The function supports filtering on string and integer column values.
		- It handles different data types and escapes values to prevent SQL
		  injection.
		- If the original query already contains a WHERE clause, the function
		  appends new conditions using the AND operator. If there is no existing
		  WHERE clause, it adds a new one.
	"""
    
	if not isinstance(original_sql_query, str):
		return original_sql_query, "original_sql_query must be a string"
	
	if not isinstance(column_value_dict, dict):
		return original_sql_query, "column_value_dict must be a dict mapping column names to values to filter on"


    # Initialize an empty list to store WHERE clauses for each column
	where_clauses = []

    # Iterate through the dictionary and create WHERE clauses for each column
	for column, values in column_value_dict.items():
		if not isinstance(column, str):
			return original_sql_query, "keys in column_value_dict must strings"
		if not isinstance(values, list):
			return original_sql_query, "values in column_value_dict must lists"
		if len(values) == 0:
			continue

		typ = type(values[0])
		if typ == str:
			strs = ["'" + s.replace("'", "") + "'" for s in values]
			in_clause = f"{column} IN ({', '.join(strs)})"
		elif typ == int:
			strs = [str(s) for s in values]
			in_clause = f"{column} IN ({', '.join(strs)})"
			in_clause = in_clause.replace("'", "")
		else:
			return original_sql_query, "column values must be strings or ints"

		# in_clause = f"{column} IN ({', '.join(['%s'] * len(values))})"
		where_clauses.append(in_clause)

    # Combine the WHERE clauses using the AND operator
	where_clause = " AND ".join(where_clauses)

    # Check if the original query already has a WHERE clause
	if 'WHERE' in original_sql_query:
        # Append the new conditions using the AND operator
		modified_sql_query = original_sql_query.replace('WHERE', f'WHERE {where_clause} AND')
	else:
        # Add a new WHERE clause
		modified_sql_query = f"{original_sql_query} WHERE {where_clause}"

	return modified_sql_query


def get_unique_column_values(table_name, columns, auth):
	"""
    Retrieve unique values from specified columns in a database table.

    This function constructs and executes SQL queries to retrieve distinct values
    from specified columns in a database table. It uses the provided authentication
    information to access the database.

    Args:
        table_name (str): The name of the database table from which to retrieve values.
        columns (list): A list of column names for which unique values are to be fetched.
        auth (dict): A dictionary containing authentication information for database access.

    Returns:
        tuple: A tuple containing two elements:
            - A dictionary where keys are column names, and values are lists of unique values.
            - An error message if an error occurred during the query execution, or None if successful.
	"""
	
	if not isinstance(table_name, str):
		return None, "ERROR: table_name must be a string"
	
	if not isinstance(columns, list):
		return None, "ERROR: columns must be a list of string"

	if len(columns) == 0:
			return None, None

	sqllist = [f"SELECT DISTINCT({column}) FROM {table_name} WITH (FLATTEN({column}))" for column in columns]

	results, err = featurebase_querybatch(
		{
			"sqllist": sqllist,
			"dbid": f"{auth.get('dbid')}",
			"db_token": f"{auth.get('db_token')}" 
		}
	)
	if err:
		return None, err

	vals = {}
	for result in results:
		vals[result.schema['fields'][0]['name']] = [v[0] for v in result.data]
	return vals, None