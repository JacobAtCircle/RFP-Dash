import dash
from dash import dcc, html, Dash, dash_table
from dash import Input, Output, State, ALL
import dash_bootstrap_components as dbc
from dash import html
import pandas as pd
import base64
import io
import boto3
import json
import mysql.connector
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text, inspect, Table, Column, Integer, String, Numeric, Boolean, Date, MetaData, select, column, text
import sqlalchemy.orm
from datetime import datetime
import fitz
from modal import build_modal
import functools

def get_secret():
    secret_name = 'BotV2ReaderCredentials'
    region_name = "us-east-1"
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except Exception as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e
    # Decrypts secret using the associated KMS key.
    secret = json.loads(get_secret_value_response['SecretString'])
    return secret

db_dict = get_secret()
aurora_engine = f'mysql+mysqlconnector://{db_dict["username"]}:{db_dict["password"]}@{db_dict["host"]}:{db_dict["port"]}/rfp'
aurora_engine = create_engine(aurora_engine)
aurora_write_engine = f'mysql+mysqlconnector://{db_dict["username"]}:{db_dict["password"]}@{db_dict["host"].replace("-ro-", "-")}:{db_dict["port"]}/rfp_fw'
aurora_write_engine = create_engine(aurora_write_engine)

# # Define the table using the Base
conn = aurora_write_engine.connect()
with conn as connection:
    result = connection.execute(text("SELECT MAX(id) FROM rfp_index"))
    max_id = result.scalar() or 0
    rfp_id = max_id + 1
conn.close()
        
#If oOrD is zero, that means origin is being used, otherwise destination
#If zOrC is zero, that means zip code list is being returned, otherwise list of country codes
def get_zip_or_country_by_city_and_state(df, dropdowns, oOrD=0, zOrC=0):
    
    cities_string = 'origin_city'
    states_string = 'origin_state'
    if oOrD == 1:
        cities_string = 'dest_city'
        states_string = 'dest_state'  
    cities = df.iloc[:, dropdowns.index(cities_string)].values.tolist() #removed +1 from dropdowns.index(cities_string) because column index was weird for google drive csv
    cities = [city.upper() for city in cities] #Convert all the city names to uppercase
    states = [state.upper() for state in df.iloc[:, dropdowns.index(states_string)].values.tolist()] #removed +1 from dropdowns.index(states_string) because column index was weird for google drive csv
    
    #Convert states to two letter abbrevs if not already
    for i in range(len(states)):
        if len(states[i]) > 2:
            abbreviation = states_abbreviations.get(states[i])
            if abbreviation is not None:
                states[i] = abbreviation

    city_state_combinations = [f"{city}-{state}" for city, state in zip(cities, states)]
    placeholders = ', '.join(['%s'] * len(city_state_combinations))
    
    sql_zip = f"""
        SELECT UPPER(post_office_city), UPPER(state) as city_state, MIN(zip)
        FROM locations
        WHERE CONCAT(UPPER(post_office_city), '-', UPPER(state)) IN ({placeholders})
        GROUP BY UPPER(post_office_city), UPPER(state)
    """
    sql_country = f"""
        SELECT UPPER(post_office_city), UPPER(state) as city_state, MIN(country)
        FROM locations
        WHERE CONCAT(UPPER(post_office_city), '-', UPPER(state)) IN ({placeholders})
        GROUP BY UPPER(post_office_city), UPPER(state)
    """

    with aurora_engine.connect() as connection:
        if zOrC == 0:
            result = connection.execute(sql_zip, city_state_combinations).fetchall()
        elif zOrC == 1:
            result = connection.execute(sql_country, city_state_combinations).fetchall()
        
        # Create a dictionary of the results
        result_dict = {row[0] + '-' + row[1]: row[2] for row in result}
        
    
    final_result = [result_dict.get(combo, None) for combo in (f"{city}-{state}" for city, state in zip(cities, states))]

    
    return final_result



#Get company names into drop-down menu
df_distributors = pd.read_csv('customers_list.csv', usecols=['tpro_id', 'customer_name'], index_col=False)
df_distributors.fillna('', inplace=True)
# Merge the two columns with a hyphen
df_distributors['merged_entry'] = df_distributors['tpro_id'] + ' - ' + df_distributors['customer_name']

#Get PODs list for drop-down menu
df_pods = pd.read_csv('pods_list.csv', index_col=False, header=None, names=['pods'])

#Get RFP Type list for drop-down menu
df_rfp_type = pd.read_csv('rfp_type.csv', index_col=False, header=None, names=['RFP Type'])

#Get branch list for drop-down menu
df_branch = pd.read_csv('branch.csv', index_col=False, header=None, names=['Branch'])

#Get year list for drop-down menu
df_rfp_year = pd.read_csv('rfp_year.csv', index_col=False, header=None, names=['RFP Year'])

#Get yes or no list for drop-down menu
df_yes_no = pd.read_csv('yes_no.csv', index_col=False, header=None, names=['yn'])

#Get rfp result list for drop-down menu
df_rfp_result = pd.read_csv('rfp_result.csv', index_col=False, header=None, names=['rfp result'])

#Get list of column header options for lanes options
options_lanes = pd.read_csv('lanes_cols.csv', index_col=False, header=None)
# Get an array of all values as strings
options_list = options_lanes.values.flatten().astype(str)

#Get columns for submitted the rfp to rfp_inex table
rfp_index_cols = pd.read_csv('rfp_index_cols.csv', index_col=False, header=None).values.flatten().astype(str)

#Get the dictionary used to convert full state names to their two letter abbrevs
with open('state_abbrev.json', 'r', encoding='utf-8') as file:
    states_abbreviations = json.load(file)


app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = html.Div([
        
        dbc.Modal(
            [
                dbc.ModalHeader("Table Preview"),
                dbc.ModalBody(
                    [
                        dash_table.DataTable(
                            id="modal-rfp",
                            columns=[],
                            data=[],
                            style_table={"height": "20vh", "overflowX": "auto"},
                            style_cell={"textAlign": "center"},
                        ),
                        html.Br(),
                        dash_table.DataTable(
                            id="modal-lanes",
                            #columns=[{"name": col, "id": col} for col in rfp_lanes_formfiller.columns],
                            data=[],
                            style_table={"height": "30vh", "overflowX": "auto"},
                            style_cell={"textAlign": "center"},
                            page_current=0, page_size=5
                        ),
                    ]
                ),
                dbc.ModalFooter(
                    dbc.Button("Close", id="modal-close", className="ml-auto")
                ),
            ],
            id="modal",
            size="xl",
            centered=True,
            style={"maxWidth": "100%", "width": "100%", "height": "65%"},
        ),
        
        
        dbc.Row([
            dbc.Col([
                dcc.Store(id='rfp-index-table'),
                dcc.Store(id='rfp-lanes-table'),
                dcc.Interval(id='timer', interval=2000, n_intervals=0),
                html.H1("FWO RFP Uploader Tool", className="display-4 text-center")
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col([
                #Dropdown list that describes what company the RFP came from
                dbc.Label('Select Distributor From List'),
                dcc.Dropdown(id='company', options=[{'label': entry, 'value': entry} for entry in df_distributors['merged_entry']], style={'text-alight': 'right'}, value='')
            ], width=8),
            dbc.Col([
                dbc.Label('Select an RFP'),
                dcc.Upload(id='upload-data', children=html.Button('Browse Files'), multiple=False),
            ], width=2),
            dbc.Col([
                dbc.Label('Status Message'),
                html.Div(id='df-success-failure'),
            ], width=2),
        ]),
        dbc.Row([
            html.Div(id='buffer3', style={'height': '25px'})
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                       html.Div(
                            style={'overflow': 'hidden'},
                            children=[
                                html.Div(
                                    id='scroll-container',
                                    style={'overflowX': 'auto'},
                                    children=[
                                        html.Div(
                                            id='list-of-dropdowns',
                                            style={'display': 'flex'},
                                            
                                        ),
                                        # dash_table.DataTable(
                                        #     id='display-csv',
                                        #     style_table={}
                                        # ),
                                        dash_table.DataTable(id='display-csv', style_cell={'width': '175px', 'minWidth': '175px', 'maxWidth': '175px', 'textAlign': 'left'}, page_current=0, page_size=10),
                                    ],
                                ),
                            ],
                        ) 
                    ]),
                ]),
            ], width=10),
            dbc.Col([
                dbc.Row([
                    html.Div(id='buffer1', style={'height': '66px'})
                ]),
                dbc.Row([
                    html.Button('Clear All', id='clear-table-button', n_clicks=0, style={'display': 'block'})
                ]),
                dbc.Row([
                    html.Div(id='buffer2', style={'height': '66px'})
                ]),
                dbc.Row([
                    html.Button('Submit', id='submit-button', n_clicks=0, style={'display': 'none'})
                ]),
                dbc.Row([
                    html.Div(id='buffer8', style={'height': '66px'})
                ]),
                dbc.Row([
                    html.Button('Preview', id='preview', n_clicks=0, style={'display': 'none'})
                ]),
            ], width=2)
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Label('RFP Type'),
                dcc.Dropdown(id='rfp-type',  options=[{'label': entry, 'value': entry} for entry in df_rfp_type['RFP Type']], value=None)
            ], width=2),
            dbc.Col([
                dbc.Label('Branch'),
                dcc.Dropdown(id='branch', options=[{'label': entry, 'value': entry} for entry in df_branch['Branch']], value=None)
            ], width=2),
            dbc.Col([
                dbc.Label('POD Name'),
                dcc.Dropdown(id='pod', options=[{'label': entry, 'value': entry} for entry in df_pods['pods']], value=None)
            ], width=1),
            dbc.Col([
                dbc.Label('RFP Year'),
                dcc.Dropdown(id='rfp-year', options=[{'label': entry, 'value': entry} for entry in df_rfp_year['RFP Year']], value=None)
            ], width=2),
            dbc.Col([  
                dbc.Row([  
                    dbc.Col([
                        #dbc.Label('Week Number'),
                        #dcc.Input(id='week-number', type='text', placeholder='# Weeks', value=None)
                    ], width=4),
                    dbc.Col([
                        dbc.Label('Lane Volume'),
                        dcc.Input(id='lane-volume', type='text', placeholder='# Lanes', value=None)
                    ], width=4),
                    dbc.Col([
                        #dbc.Label('Monthly Load'),
                        #dcc.Input(id='monthly-load', type='text', placeholder='Monthly Loads', value=None)
                    ], width=4)
                ]),
            ], width=5),
        ]),
        dbc.Row([
            html.Div(id='buffer5', style={'height':'25px'})
        ]),
        dbc.Row([
            dbc.Col([
                #dbc.Label('Monthly Est. Revenue'),
                #dcc.Input(id='monthly-revenue', type='text', placeholder='$', value=None)
            ], width=2),
            dbc.Col([
                #dbc.Label('Received Status'),
                #dcc.Dropdown(id='received-status', options=[{'label': entry, 'value': entry} for entry in df_yes_no['yn']], value=None)
            ], width=2),
            dbc.Col([
                #dbc.Label('Internal Sheet Completed'),
                #dcc.Dropdown(id='internal-sheet', options=[{'label': entry, 'value': entry} for entry in df_yes_no['yn']], value=None)
            ], width=2),
            dbc.Col([
                #dbc.Label('Submitted'),
                #dcc.Dropdown(id='rfp-submitted', options=[{'label': entry, 'value': entry} for entry in df_yes_no['yn']], value=None)
            ], width=2),
            dbc.Col([
                #dbc.Label('Multiple Rounds'),
                #dcc.Dropdown(id='multiple-rounds', options=[{'label': entry, 'value': entry} for entry in df_yes_no['yn']], value=None)
            ], width=2),
            dbc.Col([
                #dbc.Label('Hubspot'),
                #dcc.Dropdown(id='hubspot', options=[{'label': entry, 'value': entry} for entry in df_yes_no['yn']], value=None)
            ], width=2),
        ]),
        dbc.Row([
            html.Div(id='buffer4', style={'height':'25px'})
        ]),
        dbc.Row([
            dbc.Col([
                #dbc.Label('RFP Result'),
                #dcc.Dropdown(id='rfp-result', options=[{'label': entry, 'value': entry} for entry in df_rfp_result['rfp result']], value=None)
            ], width=2),
            dbc.Col([
                dbc.Label('RFP Submission Date (YYYY-MM-dd) '),
                dcc.DatePickerSingle(id='submit-date', initial_visible_month=datetime.now().strftime("%Y-%m"), display_format='Y-MM-DD', date=None, style={'width': '100%'})
            ], width=3),
            dbc.Col([
                dbc.Label('What is the name of this RFP?', style={'display': 'block'}),
                dcc.Input(id='rfp-name', type='text', placeholder='Jacob is cool', style={'width': '100%'}, value=None)
            ], width=7),
        ])
    ], style={'padding-left': '100px', 'padding-right': '100px'}
)

#Handles the input of a csv from clicking the browse button, converts it to a df, then displays it using a dash table
def parse_contents(contents):
    content_type, content_string = contents.split(',')

    if 'csv' in content_type:
        # Decode the CSV file contents and create a Pandas DataFrame
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))

        return df

    else:
        # Handle unsupported file types
        return html.Div('Unsupported file type')



# Handles the behavior of button clicks that will change the contents of the form fields
#
@app.callback(
    [Output('display-csv', 'data'),
     Output('display-csv', 'columns'),
     Output('list-of-dropdowns', 'children'),
     Output('clear-table-button', 'n_clicks'),
     Output('rfp-type', 'value'),
     Output('branch', 'value'),
     Output('pod', 'value'),
     Output('rfp-year', 'value'),
     Output('lane-volume', 'value'),
     Output('submit-date', 'date'),
     Output('rfp-name', 'value'),
     Output('preview', 'style'),
     Output('submit-button', 'style', allow_duplicate=True)],
    [Input('clear-table-button', 'n_clicks'),
    Input('upload-data', 'contents')],
    prevent_initial_callbacks = True,
    prevent_initial_call='initial_duplicate'
)
def update_output(clear_table_click, contents):

    if clear_table_click:
        return [], [], [], 0, None, None, None, None, None, None, '', {'display': 'none'}, {'display': 'none'}

    else:
        df = parse_contents(contents)
        
        dropdowns = [
                        dcc.Dropdown(
                        style={'width': '175px'},
                        id={'type': 'dynamic-dropdown', 'index': col},
                        className='my-dropdown',
                        options=[
                            {'label': option, 'value': option} for option in options_list
                        ],
                        multi=False,
                        #value=options_list[0]
                        ) for col in df.columns
                    ]
        
        return df.to_dict('records'), [{"name": i, "id": i} for i in df.columns], dropdowns, 0, None, None, None, None, df.shape[0], None, '', {'display': 'block'}, dash.no_update



# Handles the clicking of the Submit button. I want there to be a window that pops up and says, 'Does this look correct?' and displays the df
# The df should also be quickly editable. Make sure that required fields are filled out and gives the user a warning if they click submit without
# doing so. The warning should tell the user what fields need filled out.
@app.callback(
    [Output('submit-button', 'n_clicks')],
    Input('submit-button', 'n_clicks'),
     [State('company', 'value'),
     State('rfp-type', 'value'),
     State('branch', 'value'),
     State('pod', 'value'),
     State('rfp-year', 'value'),
     State('lane-volume', 'value'),
     State('submit-date', 'date'),
     State('rfp-name', 'value')],
     prevent_initial_callback = True,
)
def update_dataframe(submit_button_click, company_value, rfptype_value, branch_value, pod_value, rfpyear_value, lanevolume_value,
                        submitdate_value, rfpname_value):
    
    if submit_button_click:
        data = {
            'customer_id': [company_value.strip().split(' ')[0]],
            'rfp_name': [rfpname_value],
            'rfp_type': [rfptype_value],
            'branch': [branch_value],
            'pod': [pod_value],
            'rfp_year': [rfpyear_value],
            'lane_volume': [lanevolume_value],
            'submission_date': [submitdate_value],
        }

        df = pd.DataFrame(data)
        
        
        
        
        # # Define the table using the Base
        conn = aurora_write_engine.connect()
        
        df.to_sql(con=conn,name = 'rfp_index', if_exists='append', index=False)
        #select_stmt = select(auroa_RFPTable.c.id).where(auroa_RFPTable.c.display_name == account_display_name)
        #RFP_id = conn.execute(select_stmt).fetchone()[0]
        
        # Retrieve the primary key of the inserted row
        with conn as connection:
            result = connection.execute(text("SELECT LAST_INSERT_ID()"))
            primary_key = result.fetchone()[0]

        conn.commit()
        conn.close()

        return 0
    else:
        return dash.no_update
    


#Handles the clicking of the 'Preview' button. When this happens, a modal window will pop up showing the user 1) what will be entered in the RFP database, 
# but will also show the first 5 entries of what will go in the 'lanes' table
@app.callback(
    [Output("modal", "is_open"),
     Output('modal-rfp', 'columns'),
     Output('modal-lanes', 'columns'), 
     Output('modal-rfp', 'data'),
     Output('modal-lanes', 'data'),
     Output('submit-button', 'style')],
    [Input("preview", "n_clicks"),
     Input("modal-close", "n_clicks")],
    [State("modal", "is_open"),
     State('rfp-index-table', 'data'),
     State('rfp-lanes-table', 'data')],
     prevent_initial_callback = True,
)
def toggle_modal(n_preview_clicks, n_close_clicks, is_open, rfp_data, lanes_data):
    
    
    if n_preview_clicks or n_close_clicks:
        index_cols = [{"name": col, "id": col} for col in rfp_data.keys()]
        index_data = [dict(zip(rfp_data.keys(), values)) for values in zip(*rfp_data.values())]

        lanes_cols = [{"name": col, "id": col} for col in lanes_data.keys()]
        lanes_data = [dict(zip(lanes_data.keys(), values)) for values in zip(*lanes_data.values())]

        return not is_open, index_cols, lanes_cols, index_data, lanes_data, {'display': 'block'}
    return is_open, [], [], [], [], {'display': 'none'}


#Gets the state of various form fields as they pertain to the rfp_index table. This stores their values in JSON format to a dcc.Store module so that
#if other callbacks want to reference the data and it's structure, they can refer to the state of the store module.
@app.callback(
    Output('rfp-index-table', 'data'),
    Input('timer', 'n_intervals'),
    [State('company', 'value'),
     State('rfp-type', 'value'),
     State('branch', 'value'),
     State('pod', 'value'),
     State('rfp-year', 'value'),
     State('lane-volume', 'value'),
     State('submit-date', 'date'),
     State('rfp-name', 'value')],
     prevent_initial_callback = True,
)
def update_rfp_index_table(n_intervals, company_value, rfptype_value, branch_value, pod_value, rfpyear_value, lanevolume_value,
                            submitdate_value, rfpname_value):
    
    data = {
            'id': [str(rfp_id)],
            'customer_id': [company_value.strip().split(' ')[0]],
            'rfp_name': [rfpname_value],
            'rfp_type': [rfptype_value],
            'branch': [branch_value],
            'pod': [pod_value],
            'rfp_year': [rfpyear_value],
            'lane_volume': [lanevolume_value],
            'submission_date': [submitdate_value],
            'award_received': ['']
        }
    
    return data

#Gets the state of various form fields as they pertain to the rfp_lanes table. This stores their values in JSON format to a dcc.Store module so that
#if other callbacks want to reference the data and it's structure, they can refer to the state of the store module.
@app.callback(
    Output('rfp-lanes-table', 'data'),
    Input('preview', 'n_clicks'),
    [State({"type": "dynamic-dropdown", "index": ALL}, "value"),
     State('display-csv', 'data'),
     State('display-csv', 'columns')],
     prevent_initial_callbacks=True
)
def update_rfp_lanes_table(n_clicks, dropdowns, data, columns):
    
    lanes_data={}
    nones = [None] * len(data)
    
    if n_clicks:    
        df = pd.DataFrame(data)
        lanes_data = {
            
            'lane_id': list(range(1, len(data) + 1)),
            
            'rfp_id': [str(rfp_id)] * len(data),
            
            'origin_zip': get_zip_or_country_by_city_and_state(df, dropdowns, 0, 0) if 'origin_city' and 'origin_state' in dropdowns else nones,
            
            'origin_country': get_zip_or_country_by_city_and_state(df, dropdowns, 0, 1) if 'origin_city' and 'origin_state' in dropdowns else nones,
            
            'origin_loading_type': df.iloc[:, dropdowns.index('origin_loading_type')+1].values.tolist() if 'origin_loading_type' in dropdowns else nones,
            
            'dest_zip': get_zip_or_country_by_city_and_state(df, dropdowns, 1, 0) if 'dest_city' and 'dest_state' in dropdowns else nones,
            
            'dest_country': get_zip_or_country_by_city_and_state(df, dropdowns, 1, 1) if 'dest_city' and 'dest_state' in dropdowns else nones,
            
            'dest_loading_type': df.iloc[:, dropdowns.index('dest_loading_type')+1].values.tolist() if 'dest_loading_type' in dropdowns else nones,
            
            'dat_equipment': df.iloc[:, dropdowns.index('dat_equipment')+1].values.tolist() if 'dat_equipment' in dropdowns else nones,
            
            'actual_equipment': df.iloc[:, dropdowns.index('actual_equipment')+1].values.tolist() if 'actual_equipment' in dropdowns else nones,
            
            'team': df.iloc[:, dropdowns.index('team')+1].values.tolist() if 'team' in dropdowns else nones,
            
            'hazmat': df.iloc[:, dropdowns.index('hazmat')+1].values.tolist() if 'hazmat' in dropdowns else nones,
            
            'stops': df.iloc[:, dropdowns.index('stops')+1].values.tolist() if 'stops' in dropdowns else nones,
            
            'round_trip': df.iloc[:, dropdowns.index('round_trip')+1].values.tolist() if 'round_trip' in dropdowns else nones,
            
            'est_monthly_loads': df.iloc[:, dropdowns.index('est_monthly_loads')+1].values.tolist() if 'est_monthly_loads' in dropdowns else nones,
            
            'pc_miler_milage': df.iloc[:, dropdowns.index('pc_miler_milage')+1].values.tolist() if 'pc_miler_milage' in dropdowns else nones,
            
            'dat_15_day_average': df.iloc[:, dropdowns.index('dat_15_day_average')+1].values.tolist() if 'dat_15_day_average' in dropdowns else nones,
            
            'dat_fsc': df.iloc[:, dropdowns.index('dat_fsc')+1].values.tolist() if 'dat_fsc' in dropdowns else nones,
            
            'dat_ttt_all_in': df.iloc[:, dropdowns.index('dat_ttt_all_in')+1].values.tolist() if 'dat_ttt_all_in' in dropdowns else nones,
            
            'customer_mileage': df.iloc[:, dropdowns.index('customer_mileage')+1].values.tolist() if 'customer_mileage' in dropdowns else nones,
            
            'customer_linehaul_rate': df.iloc[:, dropdowns.index('customer_linehaul_rate')+1].values.tolist() if 'customer_linehaul_rate' in dropdowns else nones,
            
            'customer_fsc': df.iloc[:, dropdowns.index('customer_fsc')+1].values.tolist() if 'customer_fsc' in dropdowns else nones,
            
            'customer_all_in': df.iloc[:, dropdowns.index('customer_all_in')+1].values.tolist() if 'customer_all_in' in dropdowns else nones,
            
            'minimum_charge': df.iloc[:, dropdowns.index('minimum_charge')+1].values.tolist() if 'minimum_charge' in dropdowns else nones,
            
            'awarded': df.iloc[:, dropdowns.index('awarded')+1].values.tolist() if 'awarded' in dropdowns else nones,
            
            'customer_rank': df.iloc[:, dropdowns.index('customer_rank')+1].values.tolist() if 'customer_rank' in dropdowns else nones,
            
            'lev_monthly': df.iloc[:, dropdowns.index('lev_monthly')+1].values.tolist() if 'lev_monthly' in dropdowns else nones,
            
            'expected_margin': df.iloc[:, dropdowns.index('expected_margin')+1].values.tolist() if 'expected_margin' in dropdowns else nones,
            
            'margin_pct': df.iloc[:, dropdowns.index('margin_pct')+1].values.tolist() if 'margin_pct' in dropdowns else nones,
            
            'customer_rpm': df.iloc[:, dropdowns.index('customer_rpm')+1].values.tolist() if 'customer_rpm' in dropdowns else nones
        }
        

    
    return lanes_data

if __name__ == "__main__":
    app.run_server(debug=True)