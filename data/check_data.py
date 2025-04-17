import pandas as pd
import requests
from datetime import datetime
import os
import logging

# --- Configuración ---
parquet_file = os.path.join("data", "ohlc_data_60min_all_years.parquet")
print(f"Ruta absoluta del archivo OHLC: {os.path.abspath(parquet_file)}")
kraken_api_url = "https://api.kraken.com/0/public/OHLC"
kraken_pair = "XXBTZUSD"
kraken_interval = 60  # minutos

# --- Funciones ---

def inspect_parquet(file_path):
    """Inspecciona el archivo Parquet y muestra su metadata y datos."""
    try:
        print("\n--- Inspeccionando Archivo Parquet ---")
        df = pd.read_parquet(file_path)
        print(f"Archivo: {file_path}")
        print(f"Número de filas: {len(df)}")
        print(f"Columnas: {df.columns.tolist()}")
        print(f"Tipos de datos:\n{df.dtypes}")
        print("\nPrimeras 5 filas:")
        print(df.head())
        print("\nÚltimas 5 filas:")
        print(df.tail())
        print("\nEstadísticas descriptivas:")
        print(df.describe())
        print("\nValores nulos por columna:")
        print(df.isnull().sum())
        print("\nValores duplicados:")
        print(df.duplicated().sum())
        print("\nValores infinitos por columna:")
        print(df.isin([float('inf'), float('-inf')]).sum())
        print("\n--- Fin Inspección Parquet ---\n")
        return df
    except FileNotFoundError:
        print(f"Error: Archivo no encontrado: {file_path}")
        return None
    except Exception as e:
        print(f"Error al leer el archivo Parquet: {e}")
        return None

def get_kraken_data(pair, interval, since=None):
    """Obtiene datos OHLC de la API de Kraken."""
    params = {"pair": pair, "interval": interval}
    if since:
        params["since"] = since
    try:
        print("\n--- Obteniendo Datos de la API de Kraken ---")
        response = requests.get(kraken_api_url, params=params)
        response.raise_for_status()  # Lanza una excepción para errores HTTP
        data = response.json()
        if "error" in data and data["error"]:
            print(f"Error de la API de Kraken: {data['error']}")
            return None
        ohlc_data = data["result"][pair]
        df = pd.DataFrame(ohlc_data, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
        df[["open", "high", "low", "close", "vwap", "volume"]] = df[["open", "high", "low", "close", "vwap", "volume"]].apply(pd.to_numeric)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        print(f"Datos de la API de Kraken (primeras 5 filas):\n{df.head()}")
        print(f"\nDatos de la API de Kraken (últimas 5 filas):\n{df.tail()}")
        print("\n--- Fin Datos de la API de Kraken ---\n")
        return df
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión a la API de Kraken: {e}")
        return None
    except Exception as e:
        print(f"Error al procesar la respuesta de la API de Kraken: {e}")
        return None

# --- Ejecución ---

# Inspeccionar el archivo Parquet
df_parquet = inspect_parquet(parquet_file)

# Obtener datos de la API de Kraken (ejemplo)
# Puedes ajustar el 'since' para obtener datos de un período específico
df_kraken = get_kraken_data(kraken_pair, kraken_interval, since=datetime(2024, 1, 1).timestamp())

# --- Fin del Script ---
