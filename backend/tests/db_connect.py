import pymysql

try:
    connection = pymysql.connect(
        host="localhost",
        user="root",
        password="admin",
        database="sales_forecasting_app",
        port=3306,
    )
    print("✅ Successfully connected to MySQL!")
    connection.close()
except Exception as e:
    print(f"❌ Error connecting to MySQL: {e}")
