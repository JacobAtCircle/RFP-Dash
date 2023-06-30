import pandas as pd
import sqlalchemy
import json
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dependencies import Input, Output, State, ALL

#rfp_csv = pd.read_csv('rfp.csv', index_col=False)

#headers = list(rfp_csv.columns)


app = dash.Dash(__name__)

# Sample list of options
options_list = ['Option 1', 'Option 2', 'Option 3', 'Option 4']

app.layout = html.Div(
    dbc.Row([
        html.Div(
            id='dropdown-container',
            children=[
                dcc.Dropdown(
                    id={'type': 'dynamic-dropdown', 'index': index},
                    options=[
                        {'label': option, 'value': option} for option in options_list
                    ],
                    multi=True
                ) for index in range(len(options_list))
            ]
        ),
        html.Button('Submit', id='submit-button', n_clicks=0),
        html.Div(id='output-container')
    ]
)

@app.callback(
    Output('output-container', 'children'),
    [Input('submit-button', 'n_clicks')],
    [State({'type': 'dynamic-dropdown', 'index': ALL}, 'value')]
)
def handle_submit(n_clicks, dropdown_values):
    return html.Ul([
        html.Li(f"Dropdown {index}: {values}") for index, values in enumerate(dropdown_values)
    ])

if __name__ == '__main__':
    app.run_server(debug=True)