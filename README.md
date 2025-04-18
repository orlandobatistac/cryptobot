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
