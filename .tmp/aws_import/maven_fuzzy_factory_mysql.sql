CREATE TABLE IF NOT EXISTS `maven_fuzzy_maven_fuzzy_factory_data_dictionary` (`table` LONGTEXT,`field` LONGTEXT,`description` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/maven_fuzzy_factory_data_dictionary.csv' INTO TABLE `maven_fuzzy_maven_fuzzy_factory_data_dictionary` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`table`,`field`,`description`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_order_item_refunds` (`order_item_refund_id` LONGTEXT,`created_at` LONGTEXT,`order_item_id` LONGTEXT,`order_id` LONGTEXT,`refund_amount_usd` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/order_item_refunds.csv' INTO TABLE `maven_fuzzy_order_item_refunds` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`order_item_refund_id`,`created_at`,`order_item_id`,`order_id`,`refund_amount_usd`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_order_items` (`order_item_id` LONGTEXT,`created_at` LONGTEXT,`order_id` LONGTEXT,`product_id` LONGTEXT,`is_primary_item` LONGTEXT,`price_usd` LONGTEXT,`cogs_usd` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/order_items.csv' INTO TABLE `maven_fuzzy_order_items` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`order_item_id`,`created_at`,`order_id`,`product_id`,`is_primary_item`,`price_usd`,`cogs_usd`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_orders` (`order_id` LONGTEXT,`created_at` LONGTEXT,`website_session_id` LONGTEXT,`user_id` LONGTEXT,`primary_product_id` LONGTEXT,`items_purchased` LONGTEXT,`price_usd` LONGTEXT,`cogs_usd` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/orders.csv' INTO TABLE `maven_fuzzy_orders` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`order_id`,`created_at`,`website_session_id`,`user_id`,`primary_product_id`,`items_purchased`,`price_usd`,`cogs_usd`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_products` (`product_id` LONGTEXT,`created_at` LONGTEXT,`product_name` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/products.csv' INTO TABLE `maven_fuzzy_products` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`product_id`,`created_at`,`product_name`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_website_pageviews` (`website_pageview_id` LONGTEXT,`created_at` LONGTEXT,`website_session_id` LONGTEXT,`pageview_url` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/website_pageviews.csv' INTO TABLE `maven_fuzzy_website_pageviews` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`website_pageview_id`,`created_at`,`website_session_id`,`pageview_url`);
CREATE TABLE IF NOT EXISTS `maven_fuzzy_website_sessions` (`website_session_id` LONGTEXT,`created_at` LONGTEXT,`user_id` LONGTEXT,`is_repeat_session` LONGTEXT,`utm_source` LONGTEXT,`utm_campaign` LONGTEXT,`utm_content` LONGTEXT,`device_type` LONGTEXT,`http_referer` LONGTEXT);
LOAD DATA LOCAL INFILE '/Users/alejandro/PycharmProjects/omniquery-explorer/.tmp/aws_import/maven_fuzzy_factory/website_sessions.csv' INTO TABLE `maven_fuzzy_website_sessions` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '
' IGNORE 1 LINES (`website_session_id`,`created_at`,`user_id`,`is_repeat_session`,`utm_source`,`utm_campaign`,`utm_content`,`device_type`,`http_referer`);
