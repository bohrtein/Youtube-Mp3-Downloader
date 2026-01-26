import os
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import Error
import mainFiles.interfaceComponents as interfaceComponents
import mainFiles.interfaceComponents as ic

# Initialize environment variables from the .env file in the root directory
# This ensures sensitive credentials (passwords, hosts) are not hardcoded
load_dotenv()

def connect_to_db():
    """
    Establishes a connection to the MySQL database using credentials stored in .env.
    
    Returns:
        mysql.connector.connection.MySQLConnection: A connection object if successful.
        None: If the connection attempt fails.
    """
    try:
        # Retrieve configuration from environment variables via os.getenv
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            database=os.getenv('DB_NAME')
        )

        # Confirm connection status before returning the object
        if connection.is_connected():
            interfaceComponents.Print_Tag("Successfully connected to database", tag="DB Success")
            return connection

    except Error as e:
        # Catch specific MySQL driver errors (e.g., Auth failure, Host unreachable)
        interfaceComponents.Print_Tag(f"Connection failed: {e}", tag="DB Error")
        return None

def disconnect_to_db(connection):
    """
    Safely terminates the active database connection to prevent memory leaks 
    and "Too many connections" errors on the MySQL server.
    
    Args:
        connection: The MySQL connection object to be closed.
    """
    # Check if the connection exists and is currently open before attempting to close
    if connection and connection.is_connected():
        connection.close()
        interfaceComponents.Print_Tag("MySQL connection is closed", tag="DB System")