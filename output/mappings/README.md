# Source-to-Target Mappings

> Generated from `sample_data_model.xlsx` on 2026-03-18.

## Customer

| Source System | Source Table | Source Column | Target Column | Transformation                              | Notes                                 |
| ------------- | ------------ | ------------- | ------------- | ------------------------------------------- | ------------------------------------- |
| CRM           | crm_accounts | account_id    | customer_code | CAST(account_id AS STRING)                  | Natural key from CRM                  |
| CRM           | crm_accounts | name          | full_name     | TRIM(name)                                  |                                       |
| CRM           | crm_accounts | email_address | email         | LOWER(email_address)                        | Normalise to lowercase                |
| CRM           | crm_accounts | phone_number  | phone         | REGEXP_REPLACE(phone_number, '[^0-9+]', '') | Strip non-numeric                     |
| CRM           | crm_accounts | country       | country_code  | UPPER(LEFT(country, 2))                     | ISO-2 from full name — verify mapping |

## Order

| Source System | Source Table | Source Column | Target Column | Transformation                                    | Notes                    |
| ------------- | ------------ | ------------- | ------------- | ------------------------------------------------- | ------------------------ |
| OMS           | orders       | id            | order_ref     | CONCAT('ORD-', LPAD(CAST(id AS STRING), 10, '0')) | Pad to 10 digits         |
| OMS           | orders       | cust_id       | customer_id   | Lookup via customer_code                          | Join to Customer on code |
| OMS           | orders       | status        | status_code   | UPPER(status)                                     |                          |
| OMS           | orders       | placed_date   | order_date    | DATE(placed_date)                                 |                          |

## OrderItem

| Source System | Source Table | Source Column | Target Column | Transformation         | Notes                  |
| ------------- | ------------ | ------------- | ------------- | ---------------------- | ---------------------- |
| OMS           | order_lines  | order_id      | order_id      | Direct                 |                        |
| OMS           | order_lines  | prod_sku      | product_id    | Lookup via Product.sku | Join to Product on sku |
| OMS           | order_lines  | qty           | quantity      | CAST(qty AS INT64)     |                        |
| OMS           | order_lines  | price         | unit_price    | ROUND(price, 2)        | 2 decimal places       |

## Product

| Source System | Source Table | Source Column | Target Column | Transformation              | Notes            |
| ------------- | ------------ | ------------- | ------------- | --------------------------- | ---------------- |
| PIM           | products     | sku           | sku           | UPPER(TRIM(sku))            |                  |
| PIM           | products     | title         | product_name  | TRIM(title)                 |                  |
| PIM           | products     | category_name | category      | Direct                      |                  |
| PIM           | products     | cost_price    | unit_cost     | CAST(cost_price AS NUMERIC) |                  |
| PIM           | products     | active_flag   | is_active     | CAST(active_flag AS BOOL)   | 0/1 → FALSE/TRUE |

