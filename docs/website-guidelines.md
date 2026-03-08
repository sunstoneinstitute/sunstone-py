# Website Guidelines

All datasets should be published to the Sunstone website using the the CLI commands. The command reads your datasets.yaml file in order to generate a datapackage.json file and publish the relevant files, including the datapackage.json file, to Google Cloud Storage. From there, the website reads this datapackage.json file and creates a matching data package, along with all resources that are marked to publish (datasets and reports.)

Please note when first published, the data package will be imported as a draft, along with all of its resources. To publish the data package, you set its status to published to make it accessible on the website. Note that doing so will in turn make all of its datasets and reports public.

## Formatting of Datasets for Visuals and Charts

In order to render visuals and charts from datasets, the formatting of the data needs to be understandable and expected. Please follow these guidelines: 

1. No underscores in filenames or column names.
2. Datasets must be saved in CSV format only (not XLSX!).
3. Only the first row can be used for column names. 
4. Make column names readable and as short as possible. Remember they will be used in charts where there is little space. Keys like "Column Name" are better than "ColumnName".
5. Do not use row or column spanning.
6. Do not use tabs.
7. Avoid empty rows and footnotes in datasets. If needed, please make sure that the footnote appears in the first column only, and ideally starts wiht a *
8. Leave rows without data empty instead of writing 0, -, etc.
9. Filter the data as much as possible so it is relevant for your project (ie. if your original dataset has many rows, but we are only featuring a couple on the website in the form of charts, etc, only include those rows that are relevant.) We can always update the datasets to include more data later, if desired.
10. Try to keep related data in the same csv, and all of the column names across the top. Currently, datasets cannot be combined for single visuals, so it all needs to be in one csv to show in a single chart.
11. All data in the CSVs should be in English. 
12. All column names and values should be presentable to the user. For example, if you translated a row, you should remove the old row to avoid confusion.
