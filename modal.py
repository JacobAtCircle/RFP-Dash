import dash
from dash import dcc, html, Dash, dash_table
from dash import Input, Output, State
import dash_bootstrap_components as dbc
from dash import html
import pandas as pd

def build_modal(df):
    # Convert DataFrame to an HTML table
    table = dbc.Table.from_dataframe(df, striped=True, bordered=True, hover=True)

    modal = dbc.Modal(
        [
            dbc.ModalHeader("DataFrame Preview"),
            dbc.ModalBody(table),
            dbc.ModalFooter(
                dbc.Button("Yes", id="modal-yes-button", className="mr-2"),
                dbc.Button("Go Back", id="modal-go-back-button", className="mr-2"),
            ),
        ],
        id="modal",
        centered=True,
    )

    return modal
