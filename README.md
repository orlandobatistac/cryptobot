# CryptoBot 🚀

**CryptoBot** is an experimental, AI-assisted cryptocurrency trading bot built to backtest technical strategies, optimize parameters, and generate performance insights using historical market data. This MVP represents the starting point of a much bigger journey—one where artificial intelligence, automation, and curiosity merge.

> 🧠 Built entirely by a human (me) and a team of AI assistants including Grok, Gemini, GitHub Copilot, and ChatGPT. Just me and the machines—no team, no investors. Just code, learning, and innovation.

---

## 🌟 Why CryptoBot?

This project began as a personal mission to learn Python and explore the power of artificial intelligence in real-world applications. While the long-term goal is to build a live-trading AI bot, **CryptoBot** is the first working MVP focused on:

- 📈 Strategy development & backtesting
- 🔍 Hyperparameter tuning with Optuna
- 📊 Visualizing and interpreting results
- 🤖 Creating the foundation for AI-driven trading

It’s not perfect—but it’s proof of how far self-learning and AI co-creation can go.

---

## 🧠 Technologies & Tools

- **Python 3.8+**
- **Optuna** – For hyperparameter optimization
- **pandas, numpy** – Data wrangling
- **mplfinance** – Candlestick charting
- **tqdm, colorama** – CLI progress feedback
- **pyarrow** – Reading `.parquet` data files
- **AI Assistants Used**: Grok AI, OpenAI (ChatGPT), Gemini Code Assist, GitHub Copilot

---

## 📁 Project Structure

```
cryptobot/
├── backtest.py               # Core backtesting engine
├── config.json               # Strategy and system configuration
├── data.py                   # Data loading & filtering
├── live_paper.py             # Paper trading loop (simulated live trading)
├── logger.py                 # Logging system
├── main.py                   # Main runner with progress bar
├── optimize.py               # Strategy optimization via Optuna
├── strategy.py               # Indicators + entry/exit logic
├── requirements.txt          # Python dependencies
├── debug.log                 # Execution logs
├── paper_trades.db           # SQLite database for paper trading
├── README.md                 # You’re here!
├── data/
│   ├── update_data.py        # Script to update/download OHLC data
│   ├── check_data.py         # Script to inspect and validate OHLC data
│   └── ohlc_data_60min_all_years.parquet # Main OHLC data file
└── results/                  # All output results
    └── backtest/             # Backtest results (metrics, trades, plots)
```

---

## 🆕 Main Features & Scripts

- **backtest.py**: Core backtesting engine for strategies.
- **main.py**: Main pipeline runner (can generate demo data).
- **optimize.py**: Hyperparameter optimization using Optuna.
- **strategy.py**: Technical indicators and entry/exit logic.
- **live_paper.py**: Simulated live trading (paper trading) loop with real-time monitoring and database logging.
- **data/update_data.py**: Downloads and updates OHLC data from Kraken, handles incremental updates and logging.
- **data/check_data.py**: Inspects, validates, and summarizes OHLC data files; can fetch and compare with Kraken API.
- **logger.py**: Centralized logging to debug.log.
- **paper_trades.db**: SQLite database for storing simulated trades.

---

## ⚙️ Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/cryptobot.git
cd cryptobot
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. (Optional) Generate sample data

```bash
python main.py  # config.json allows generating demo data
```

---

## 🏁 Usage

1. Configure your bot in `config.json`
2. Run the full pipeline:

```bash
python main.py
```

3. Results will be saved in `results/backtest/YYYYMMDD_HHMMSS/` with:
   - `metrics.json`: Performance metrics
   - `trades.json`: Trade logs
   - `plot.png`: Strategy signal visualization

---

## 🧠 Optimization (Optuna)

To run strategy optimization:

```bash
python optimize.py
```

Best parameters are saved in:

```
results/optimization/best_config_*.json
```

---

## Automatic Strategy Evaluation (D1 Candle)

The bot automatically evaluates the trading strategy at the close of each daily (D1) candle, while monitoring and user interaction remain real-time during each cycle.

### How it works

- **Data Loading and Resampling:**
  - On each cycle, the bot loads OHLC data (60min) and resamples it to the configured interval (default: daily/D1).
- **Automatic Evaluation:**
  - After displaying the current state, the bot runs:
    - `strategy.calculate_indicators(df_resampled)` to compute indicators.
    - It checks the last daily candle.
    - If `strategy.entry_signal(last_candle, df_resampled)` returns True and there is no open position, it triggers an automatic buy.
    - If `strategy.exit_signal(last_candle, df_resampled)` returns True and there is an open position, it triggers an automatic sell.
- **Order Simulation and Logging:**
  - Before saving the trade, the order is validated with the Kraken API (using validate=True for paper trading).
  - If validation is successful, the trade is saved to the database.

### What this means

- The bot automatically checks, on each cycle, whether to open or close a position based on your strategy logic, using the latest daily candle.
- No manual intervention is required for the strategy to operate; the bot acts autonomously, but you can monitor or intervene manually at any time.

---

## 📝 Paper Trading (Realistic Simulated Environment)

To validate your strategy in a realistic environment, `live_paper.py` provides a paper trading loop: each day (at the close of the D1 candle) the bot evaluates your strategy and logs every trade to **paper_trades.db**.

### 1. Setup

- Make sure `config.json` contains your desired parameters.
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Running Paper Trading

1. Run:
   ```bash
   python live_paper.py
   ```
2. The bot will display a table with status (cycle, time, price, open trade, P/L, equity or balance).
3. Commands available during execution:
   - `b` → buy at the current price (simulated).
   - `s` → sell (close position).
   - `q` → exit the bot.

### 3. Trade Verification

- Query the recorded trades in SQLite:
  ```bash
  sqlite3 paper_trades.db "SELECT timestamp, type, price, volume, profit, balance, source FROM trades;"
  ```
- Verify that:
  - Each row has type `auto` or `manual`.
  - The `timestamp` matches the on-screen table.
  - No tiny negative values exist in `balance`.

### 4. Reproducible Tests

- **Replay vs Backtest:** Run `test_replay.py` to verify entry/exit signals match `results/backtest/.../trades.json`.
- **DB Stability Test:** In parallel, run multiple cycles or threads simulating data reloads and buy/sell commands. Verify there are no database locks.

---

With this section, you can thoroughly test your bot in a simulated environment, confirm the correct recording of trades, and ensure system stability under production-like conditions.

---

## 📌 Notes

- This bot **does not connect to exchanges** (yet).
- Data must include: `Timestamp`, `Open`, `High`, `Low`, `Close`, `Volume`
- You can use your own `.parquet` or `.csv` files in `data/`

---

## 📜 License

MIT — feel free to fork, modify, and build something awesome!

---

## 👨‍💻 About the Developer

Hi, I'm Orlando. This project represents the **beginning** of my AI journey. CryptoBot was born out of curiosity, passion, and a deep desire to learn how far artificial intelligence can take us. What started as a learning experiment quickly became one of the most exciting things I've ever built—with no team, just AI tools and determination.

> I believe this is just the beginning of many amazing projects to come.

---

## 📫 Contact

- Email: orlandobatistac@gmail.com
- GitHub: [github.com/orlandobatistac](https://github.com/orlandobatistac)
- LinkedIn: [linkedin.com/in/orlando-batista-curiel](https://linkedin.com/in/orlando-batista-curiel)

---

Thanks for visiting my project. If you like it, star it 🌟 and stay tuned for future versions with live AI trading.
