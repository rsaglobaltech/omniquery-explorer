CREATE TABLE IF NOT EXISTS "restaurant_orders_menu_items" ("menu_item_id" TEXT,"item_name" TEXT,"category" TEXT,"price" TEXT);
\copy "restaurant_orders_menu_items" ("menu_item_id","item_name","category","price") FROM '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/restaurant_orders/Restaurant Orders/menu_items.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE IF NOT EXISTS "restaurant_orders_order_details" ("order_details_id" TEXT,"order_id" TEXT,"order_date" TEXT,"order_time" TEXT,"item_id" TEXT);
\copy "restaurant_orders_order_details" ("order_details_id","order_id","order_date","order_time","item_id") FROM '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/restaurant_orders/Restaurant Orders/order_details.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE IF NOT EXISTS "restaurant_orders_restaurant_db_data_dictionary" ("table" TEXT,"field" TEXT,"description" TEXT);
\copy "restaurant_orders_restaurant_db_data_dictionary" ("table","field","description") FROM '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/restaurant_orders/Restaurant Orders/restaurant_db_data_dictionary.csv' WITH (FORMAT csv, HEADER true);
