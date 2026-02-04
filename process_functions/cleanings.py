import pandas as pd
import datetime


def update_date_col(df, col_name_selected):
    """Standardizes date column naming and format."""
    df = df.copy()
    df = df.rename(columns={col_name_selected: "Date"})
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    return df


def get_coincidences(df_ci, df_co, nickname_col):
    """
    Finds listings present in both Check-In and Check-Out for the same day.
    """
    set_ci = set(df_ci[nickname_col].unique())
    set_co = set(df_co[nickname_col].unique())
    # Intersection finds nicknames present in BOTH sets
    return list(set_ci.intersection(set_co))


def create_bydate_reservations(ci, co, config):
    """
    Iterates through dates to build the summary report.
    Dynamically creates a calendar based on the data provided.
    """


    # 1. Get the full range of dates available across both files
    all_dates = pd.concat([ci['Date'], co['Date']]).dropna()

    if all_dates.empty:
        return pd.DataFrame()  # Return empty if no data

    fecha_inicio = all_dates.min()
    fecha_fin = all_dates.max()

    # 2. Generate the calendar range
    calendar_dates = pd.date_range(start=fecha_inicio, end=fecha_fin).date

    nick_col = config['nick']
    code_col = config['code']

    results = []

    for date_s in calendar_dates:
        # Filter data for the specific day
        day_ci = ci[ci["Date"] == date_s]
        day_co = co[co["Date"] == date_s]

        coincidences = get_coincidences(day_ci, day_co, nick_col)

        results.append({
            'Date': date_s,
            'week_day': date_s.strftime('%A'),
            'checkIn': day_ci[code_col].count(),
            'checkOut': day_co[code_col].count(),
            'coincidencias': len(coincidences),
            'listings': coincidences,
            'listings_ci': day_ci[nick_col].tolist(),
            'listings_co': day_co[nick_col].tolist()
        })

    return pd.DataFrame(results)


def run_frecuency(file_checkIn_path, file_checkOut_path, columns, selected_col1, selected_col2):
    """
    Main entry point to process files and return the formatted DataFrame.
    """
    # Load files if paths are provided, otherwise assume they are already DataFrames
    cin = pd.read_csv(file_checkIn_path) if isinstance(file_checkIn_path, str) else file_checkIn_path
    cout = pd.read_csv(file_checkOut_path) if isinstance(file_checkOut_path, str) else file_checkOut_path

    ci = update_date_col(cin, selected_col1)
    co = update_date_col(cout, selected_col2)

    # Determine schema (CSV vs API) based on provided columns
    if "listing.nickname" in columns or "listing.nickname" in ci.columns:
        config = {'nick': 'listing.nickname', 'code': 'confirmationCode'}
    else:
        config = {'nick': "LISTING'S NICKNAME", 'code': 'CONFIRMATION CODE'}

    return create_bydate_reservations(ci, co, config)


def open_csv_files():
    """
    Configuration and execution function.
    """
    file_check_in = r"C:\Users\Wellcome\PycharmProjects\dailyPayments\files_frecuency\new_bogota\checkin_bog.csv"
    file_check_out = "./files_frecuency/new_bogota/checkout_bog.csv"

    # These columns help the script decide which naming convention to use
    columns = ['CONFIRMATION CODE', 'CHECK-IN DATE', 'LISTING\'S NICKNAME']

    reservations = run_frecuency(
        file_check_in,
        file_check_out,
        columns,
        'CHECK-IN DATE',
        'CHECK-OUT DATE'
    )
    return reservations

