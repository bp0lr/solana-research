import base58
import re
import time
import ctypes
from datetime import datetime
from multiprocessing import Process, Value, Queue, cpu_count
from nacl.signing import SigningKey
import numpy as np
import numpy.typing as npt
from numba import njit, prange
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
import requests
import json
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from rich.console import Console
from rich.table import Table
import base58
import time
from rich.live import Live
from rich.panel import Panel
import secrets
import re
from nacl.signing import SigningKey
from nacl.public import PrivateKey
import multiprocessing
import os
from multiprocessing import Process, Queue, Value, cpu_count
import ctypes
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from numba import jit, njit, prange
import numpy.typing as npt

def generate_keypair():
    """Generate a new Ed25519 keypair for Solana in Phantom wallet format."""
    signing_key = SigningKey.generate()
    secret_key = bytes(signing_key)  # 32 bytes private key
    verify_key = bytes(signing_key.verify_key)  # 32 bytes public key
    
    # Combine into a 64-byte array (Phantom wallet format)
    full_keypair = secret_key + verify_key
    return full_keypair

def get_public_key(private_key: bytes) -> str:
    """Get public key from private key"""
    return base58.b58encode(private_key).decode('ascii')[:44]  # First 44 chars is roughly the public key length

class SolscanAPI:
    def __init__(self):
        self.base_url = 'https://api-v2.solscan.io/v2'
        self.headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-GB,en;q=0.8',
            'origin': 'https://solscan.io',
            'priority': 'u=1, i',
            'referer': 'https://solscan.io/',
            'sec-ch-ua': '"Not(A:Brand";v="99", "Brave";v="133", "Chromium";v="133"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sec-gpc': '1',
            'sol-aut': '4iOtUjKOhwGFLxtTMWPOVZB9dls0fKyJ0pVfH-hN',
            'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InNhbmRlcmJ1cnVtYUBmYXN0bWFpbC5ubCIsImFjdGlvbiI6ImxvZ2dlZCIsImlhdCI6MTczOTAzMTY5NiwiZXhwIjoxNzQ5ODMxNjk2fQ.29Lfnoni9KO_oRjyr0M6pjcXzNc3N2d-mQEAStpw2eA',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
        }
        self.console = Console()

    def _make_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """
        Make a request to the Solscan API
        """
        url = f'{self.base_url}/{endpoint}'
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request: {e}")
            return None

    def get_account_balance(self, address: str) -> Optional[float]:
        """
        Get the balance of a Solana account in SOL
        """
        data = self._make_request(f'account?address={address}')
        if data and data.get('success'):
            lamports = int(data['data'].get('lamports', 0))
            sol_balance = lamports / 1_000_000_000  # Convert to SOL
            return sol_balance
        return None

    def get_account_transactions(self, address: str, page: int = 1, page_size: int = 10) -> Optional[List[Dict[str, Any]]]:
        """
        Get transaction history for a Solana account
        """
        endpoint = f'account/transfer?address={address}&page={page}&page_size={page_size}&remove_spam=true&exclude_amount_zero=true'
        data = self._make_request(endpoint)
        
        if data and data.get('success'):
            return data.get('data', [])
        return None

    def get_dex_trading_history(self, address: str) -> List[Dict[str, Any]]:
        """
        Get complete DEX trading history for an account
        """
        page = 1
        page_size = 100
        all_trades = []
        
        while True:
            endpoint = f'account/activity/dextrading?address={address}&page={page}&page_size={page_size}'
            data = self._make_request(endpoint)
            
            if not data or not data.get('success') or not data.get('data'):
                break
                
            trades = data['data']
            if not trades:
                break
                
            all_trades.extend(trades)
            if len(trades) < page_size:
                break
                
            page += 1
        
        return all_trades

    def get_token_price(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Get token price and metadata from Solscan API
        Returns a dictionary containing price in USDT and other token information
        """
        data = self._make_request(f'account?address={token_address}')
        if data and data.get('success'):
            metadata = data.get('metadata', {})
            token_info = data.get('data', {}).get('tokenInfo', {})
            token_metadata = data.get('metadata', {}).get('tokens', {}).get(token_address, {})
            
            return {
                'price_usdt': token_metadata.get('price_usdt', 0),
                'decimals': token_info.get('decimals', 0),
                'name': metadata.get('data', {}).get('name', ''),
                'symbol': metadata.get('data', {}).get('symbol', '')
            }
        return None

def display_transactions_table(transactions: List[Dict[str, Any]], console: Console, input_address: str):
    """
    Display transactions in a rich table format
    """
    table = Table(title="Transaction History")
    
    # Add columns
    table.add_column("Time", justify="left", style="cyan")
    table.add_column("Type", justify="center", style="magenta")
    table.add_column("Amount (SOL)", justify="right", style="green")
    table.add_column("From", justify="right")
    table.add_column("To", justify="left")
    table.add_column("Value (USD)", justify="right", style="yellow")
    
    # Add rows
    for tx in transactions:
        timestamp = datetime.fromtimestamp(tx['block_time']).strftime('%Y-%m-%d %H:%M')
        amount = float(tx['amount']) / (10 ** tx['token_decimals'])
        direction = "→" if tx['flow'] == 'out' else "←"
        
        # Format addresses with styles inline
        from_addr = f"[dim]{f'...{tx['from_address'][-5:]}'}" if tx['from_address'] == input_address else f"[blue]{f'...{tx['from_address'][-5:]}'}"
        to_addr = f"[dim]{f'...{tx['to_address'][-5:]}'}" if tx['to_address'] == input_address else f"[blue]{f'...{tx['to_address'][-5:]}'}"
        
        table.add_row(
            timestamp,
            tx['activity_type'].replace('ACTIVITY_', ''),
            f"{amount:.4f} {direction}",
            from_addr,
            to_addr,
            f"${tx.get('value', 0):.2f}",
            end_section=True  # Add subtle separator between rows
        )
    
    console.print(table)

def display_balance_history(transactions: List[Dict[str, Any]], current_balance: float, console: Console, input_address: str):
    """
    Display balance history by analyzing transactions
    """
    table = Table(title="Balance History")
    
    # Add columns
    table.add_column("Time", justify="left", style="cyan")
    table.add_column("Transaction", justify="center", style="magenta")
    table.add_column("Change", justify="right", style="green")
    table.add_column("Balance", justify="right", style="yellow")
    
    # Calculate balance changes starting from current balance
    balance = current_balance
    balance_history: List[Tuple[datetime, str, float, float]] = []
    
    for tx in reversed(transactions):  # Process oldest to newest
        timestamp = datetime.fromtimestamp(tx['block_time'])
        amount = float(tx['amount']) / (10 ** tx['token_decimals'])
        
        if tx['flow'] == 'out':
            old_balance = balance + amount
            change = f"-{amount:.4f}"
        else:
            old_balance = balance - amount
            change = f"+{amount:.4f}"
            
        balance_history.append((timestamp, tx['activity_type'].replace('ACTIVITY_', ''), amount, old_balance))
        balance = old_balance
    
    # Display in chronological order
    for timestamp, tx_type, amount, bal in balance_history:
        change_color = "red" if amount < 0 else "green"
        table.add_row(
            timestamp.strftime('%Y-%m-%d %H:%M'),
            tx_type,
            f"[{change_color}]{'+' if amount > 0 else '-'}{abs(amount):.4f}[/{change_color}]",
            f"{bal:.4f}",
            end_section=True
        )
    
    # Add current balance as last row
    table.add_row(
        "[bold]Current[/bold]",
        "",
        "",
        f"[bold yellow]{current_balance:.4f}[/bold yellow]"
    )
    
    console.print(table)

def format_token_amount(amount: float) -> str:
    """Format token amount in k/m/b format"""
    if amount >= 1_000_000_000:
        return f"{amount/1_000_000_000:.1f}B"
    elif amount >= 1_000_000:
        return f"{amount/1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"{amount/1_000:.1f}k"
    else:
        return f"{amount:.0f}"

def format_token_address(address: str) -> str:
    """Format token address to show first 4 and last 4 characters"""
    if address == "So11111111111111111111111111111111111111112" or address == "So11111111111111111111111111111111111111111":
        return "SOL"
    return f"{address[:4]}...{address[-4:]}"

def display_dex_trading_summary(trades: List[Dict[str, Any]], console: Console, wallet_address: str):
    """
    Display DEX trading summary grouped by token and save to CSV
    """
    # Dictionary to track token stats
    token_stats = {}
    period_stats = {
        '24h': {'invested': 0, 'received': 0, 'start_time': datetime.now().timestamp() - 86400},
        '7d': {'invested': 0, 'received': 0, 'start_time': datetime.now().timestamp() - 7 * 86400},
        '30d': {'invested': 0, 'received': 0, 'start_time': datetime.now().timestamp() - 30 * 86400}
    }
    SOL_ADDRESSES = {
        "So11111111111111111111111111111111111111112",
        "So11111111111111111111111111111111111111111"
    }

    def is_sol_token(token: str) -> bool:
        """Check if a token is SOL"""
        return token in SOL_ADDRESSES
    
    # First pass: collect all trades and update period stats
    for trade in trades:
        amount_info = trade.get('amount_info', {})
        if not amount_info:
            continue
            
        # Extract token information from amount_info
        token1 = amount_info.get('token1')
        token2 = amount_info.get('token2')
        token1_decimals = amount_info.get('token1_decimals', 0)
        token2_decimals = amount_info.get('token2_decimals', 0)
        
        # Safely convert amounts to float with null checks
        try:
            amount1_raw = amount_info.get('amount1')
            amount2_raw = amount_info.get('amount2')
            amount1 = float(amount1_raw if amount1_raw is not None else 0) / (10 ** token1_decimals)
            amount2 = float(amount2_raw if amount2_raw is not None else 0) / (10 ** token2_decimals)
        except (ValueError, TypeError):
            # Skip this trade if amounts are invalid
            continue
        
        trade_time = datetime.fromtimestamp(trade['block_time'])
        trade_timestamp = trade['block_time']
        
        # Update period stats
        for period, stats in period_stats.items():
            if trade_timestamp >= stats['start_time']:
                if is_sol_token(token1):
                    stats['invested'] += amount1
                elif is_sol_token(token2):
                    stats['received'] += amount2
        
        # Initialize token stats if needed
        for token in [token1, token2]:
            if token and token not in token_stats and not is_sol_token(token):
                token_stats[token] = {
                    'sol_invested': 0,  # SOL spent to buy this token
                    'sol_received': 0,  # SOL received from selling this token
                    'tokens_bought': 0,  # Amount of tokens bought
                    'tokens_sold': 0,    # Amount of tokens sold
                    'last_trade': None,
                    'last_sol_rate': 0,  # Last known SOL/token rate
                    'token_price_usdt': 0,  # Current token price in USDT
                    'decimals': 0,  # Token decimals
                    'name': '',  # Token name
                    'symbol': ''  # Token symbol
                }
        
        # Update stats based on trade direction
        if is_sol_token(token1):
            # Sold SOL for tokens
            if token2:
                token_stats[token2]['sol_invested'] += amount1
                token_stats[token2]['tokens_bought'] += amount2
                token_stats[token2]['last_sol_rate'] = amount1 / amount2  # SOL per token
                token_stats[token2]['last_trade'] = max(trade_time, token_stats[token2]['last_trade']) if token_stats[token2]['last_trade'] else trade_time
        elif is_sol_token(token2):
            # Sold tokens for SOL
            if token1:
                token_stats[token1]['sol_received'] += amount2
                token_stats[token1]['tokens_sold'] += amount1
                token_stats[token1]['last_sol_rate'] = amount2 / amount1  # SOL per token
                token_stats[token1]['last_trade'] = max(trade_time, token_stats[token1]['last_trade']) if token_stats[token1]['last_trade'] else trade_time
    
    # Fetch current token prices for tokens with remaining balance
    api = SolscanAPI()
    sol_price = api.get_token_price("So11111111111111111111111111111111111111112")
    sol_price_usdt = sol_price.get('price_usdt', 0) if sol_price else 0
    
    console.print("\n[yellow]Fetching current token prices...[/yellow]")
    for token, stats in token_stats.items():
        remaining_tokens = stats['tokens_bought'] - stats['tokens_sold']
        if remaining_tokens >= 100:  # Only fetch price if significant remaining balance
            token_data = api.get_token_price(token)
            if token_data:
                stats['token_price_usdt'] = token_data.get('price_usdt', 0)
                stats['decimals'] = token_data.get('decimals', 0)
                stats['name'] = token_data.get('name', '')
                stats['symbol'] = token_data.get('symbol', '')
    
    # Create and display the summary table
    table = Table(title="DEX Trading Summary")
    table.add_column("Token", justify="left", style="cyan", width=12)
    table.add_column("SOL Invested", justify="right", style="green")
    table.add_column("SOL Received", justify="right", style="red")
    table.add_column("SOL Profit", justify="right", style="yellow")
    table.add_column("Remaining Value", justify="right", style="magenta")
    table.add_column("Total Profit", justify="right", style="blue")
    table.add_column("Token Price", justify="right", style="cyan")
    table.add_column("Last Trade", justify="left", style="dim")
    
    # Sort by last trade date
    sorted_tokens = sorted(
        [(k, v) for k, v in token_stats.items() if not is_sol_token(k)],
        key=lambda x: x[1]['last_trade'] if x[1]['last_trade'] else datetime.min,
        reverse=True
    )
    
    # Track totals
    total_invested = 0
    total_received = 0
    total_profit = 0
    total_remaining = 0
    
    # Prepare CSV data
    os.makedirs('reports', exist_ok=True)
    csv_file = f'reports/{wallet_address}.csv'
    with open(csv_file, 'w') as f:
        f.write("Token,SOL Invested,SOL Received,SOL Profit,Remaining Value,Total Profit,Token Price (USDT),Last Trade\n")
        
        for token, stats in sorted_tokens:
            remaining_tokens = stats['tokens_bought'] - stats['tokens_sold']
            sol_profit = stats['sol_received'] - stats['sol_invested']
            
            # Calculate remaining value using current token price if available
            if stats['token_price_usdt'] > 0 and sol_price_usdt > 0:
                remaining_value = (remaining_tokens * stats['token_price_usdt']) / sol_price_usdt
            else:
                remaining_value = remaining_tokens * stats['last_sol_rate']
            
            total_token_profit = sol_profit + remaining_value
            
            total_invested += stats['sol_invested']
            total_received += stats['sol_received']
            total_profit += sol_profit
            total_remaining += remaining_value
            
            profit_color = "green" if sol_profit >= 0 else "red"
            total_profit_color = "green" if total_token_profit >= 0 else "red"
            
            # Format token price display
            token_price_display = f"${stats['token_price_usdt']:.6f}" if stats['token_price_usdt'] > 0 else "N/A"
            
            # Add to table
            table.add_row(
                format_token_address(token),
                f"{stats['sol_invested']:.3f} ◎",
                f"{stats['sol_received']:.3f} ◎",
                f"[{profit_color}]{sol_profit:+.3f} ◎[/{profit_color}]",
                f"{remaining_value:.3f} ◎",
                f"[{total_profit_color}]{total_token_profit:+.3f} ◎[/{total_profit_color}]",
                token_price_display,
                stats['last_trade'].strftime('%Y-%m-%d %H:%M') if stats['last_trade'] else 'N/A'
            )
            
            # Write to CSV
            f.write(f"{token},{stats['sol_invested']:.3f},{stats['sol_received']:.3f},{sol_profit:.3f},{remaining_value:.3f},{total_token_profit:.3f},{stats['token_price_usdt']:.6f},{stats['last_trade'].strftime('%Y-%m-%d %H:%M') if stats['last_trade'] else 'N/A'}\n")
    
        # Add totals to CSV
        total_overall_profit = total_profit + total_remaining
        f.write(f"TOTAL,{total_invested:.3f},{total_received:.3f},{total_profit:.3f},{total_remaining:.3f},{total_overall_profit:.3f},,\n")
    
    # Add totals row to table
    profit_style = "green" if total_profit >= 0 else "red"
    total_profit_style = "green" if total_overall_profit >= 0 else "red"
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_invested:.3f} ◎[/bold]",
        f"[bold]{total_received:.3f} ◎[/bold]",
        f"[bold][{profit_style}]{total_profit:+.3f} ◎[/{profit_style}][/bold]",
        f"[bold]{total_remaining:.3f} ◎[/bold]",
        f"[bold][{total_profit_style}]{total_overall_profit:+.3f} ◎[/{total_profit_style}][/bold]",
        "",
        "",
        end_section=True
    )
    
    console.print(table)
    console.print(f"\n[yellow]Report saved to {csv_file}[/yellow]")
    
    # Calculate and display ROI for different periods
    console.print("\n[bold]Return on Investment (ROI)[/bold]")
    roi_table = Table(show_header=True, header_style="bold")
    roi_table.add_column("Period", style="cyan")
    roi_table.add_column("SOL Invested", justify="right", style="green")
    roi_table.add_column("SOL Received", justify="right", style="red")
    roi_table.add_column("Profit/Loss", justify="right", style="yellow")
    roi_table.add_column("ROI %", justify="right", style="magenta")
    
    # Track remaining value per period
    period_remaining_value = {
        '24h': 0,
        '7d': 0,
        '30d': 0
    }
    
    # Calculate remaining value for each period using current token prices
    current_time = datetime.now().timestamp()
    for token, stats in token_stats.items():
        remaining_tokens = stats['tokens_bought'] - stats['tokens_sold']
        
        # Calculate remaining value using current token price if available
        if stats['token_price_usdt'] > 0 and sol_price_usdt > 0:
            remaining_value = (remaining_tokens * stats['token_price_usdt']) / sol_price_usdt
        else:
            remaining_value = remaining_tokens * stats['last_sol_rate']
        
        if stats['last_trade']:
            last_trade_time = stats['last_trade'].timestamp()
            # Add remaining value to each period where the last trade falls within the period
            if last_trade_time >= current_time - 86400:  # 24h
                period_remaining_value['24h'] += remaining_value
            if last_trade_time >= current_time - 7 * 86400:  # 7d
                period_remaining_value['7d'] += remaining_value
            if last_trade_time >= current_time - 30 * 86400:  # 30d
                period_remaining_value['30d'] += remaining_value
    
    for period, stats in period_stats.items():
        if stats['invested'] > 0:
            # Include remaining value in profit calculation
            total_received = stats['received'] + period_remaining_value[period]
            profit = total_received - stats['invested']
            roi_percent = (profit / stats['invested']) * 100
            profit_color = "green" if profit >= 0 else "red"
            roi_color = "green" if roi_percent >= 0 else "red"
            
            roi_table.add_row(
                period.upper(),
                f"{stats['invested']:.3f} ◎",
                f"{total_received:.3f} ◎",  # Show total including remaining value
                f"[{profit_color}]{profit:+.3f} ◎[/{profit_color}]",
                f"[{roi_color}]{roi_percent:+.2f}%[/{roi_color}]"
            )
        else:
            roi_table.add_row(
                period.upper(),
                "0.000 ◎",
                "0.000 ◎",
                "0.000 ◎",
                "N/A"
            )
    
    console.print(roi_table)

    # Count transactions
    total_defi_txs = len(trades)
    non_sol_txs = 0

    for trade in trades:
        amount_info = trade.get('amount_info', {})
        if not amount_info:
            continue
            
        token1 = amount_info.get('token1')
        token2 = amount_info.get('token2')
        
        # Count if neither token is SOL
        if token1 and token2 and token1 not in SOL_ADDRESSES and token2 not in SOL_ADDRESSES:
            non_sol_txs += 1

    # Display transaction summary
    summary_table = Table(show_header=True, header_style="bold")
    summary_table.add_column("Transaction Type", style="cyan")
    summary_table.add_column("Count", justify="right", style="yellow")
    summary_table.add_column("Percentage", justify="right", style="green")

    summary_table.add_row(
        "Total DeFi Transactions",
        str(total_defi_txs),
        "100%"
    )
    summary_table.add_row(
        "Non-SOL Token Swaps",
        str(non_sol_txs),
        f"{(non_sol_txs/total_defi_txs*100):.1f}%" if total_defi_txs > 0 else "0%"
    )
    summary_table.add_row(
        "SOL-Involved Swaps",
        str(total_defi_txs - non_sol_txs),
        f"{((total_defi_txs-non_sol_txs)/total_defi_txs*100):.1f}%" if total_defi_txs > 0 else "0%"
    )

    console.print("\n[bold]Transaction Summary[/bold]")
    console.print(summary_table)

def print_usage():
    """
    Print usage information
    """
    print("\nSolana Research Tool Usage:")
    print("==========================")
    print("-1 <address>     Get Account Balance")
    print("-2 <address>     View Transaction History")
    print("-3 <address>     View Balance History")
    print("-4 <pattern>     Generate Vanity Address")
    print("\nExamples:")
    print("python main.py -1 AqEvrwvsNad9ftZaPneUrjTcuY2o7RGkeuqknbT91VnY")
    print("python main.py -3 AqEvrwvsNad9ftZaPneUrjTcuY2o7RGkeuqknbT91VnY")
    print("python main.py -4 \"abc$\"")
    print("==========================")

# Pre-compile regex patterns for better performance
REGEX_CACHE = {}

@njit(cache=True)
def fast_check_pattern(public_key_bytes: npt.NDArray[np.uint8], pattern_bytes: npt.NDArray[np.uint8]) -> bool:
    """JIT-compiled pattern matching for simple contains check"""
    n, m = len(public_key_bytes), len(pattern_bytes)
    for i in range(n - m + 1):
        match = True
        for j in range(m):
            if public_key_bytes[i + j] != pattern_bytes[j]:
                match = False
                break
        if match:
            return True
    return False

@njit(parallel=True, cache=True)
def parallel_check_keypairs(public_keys: npt.NDArray[np.uint8], pattern: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """Check multiple public keys in parallel using Numba, returns array of match flags"""
    n = len(public_keys)
    results = np.zeros(n, dtype=np.uint8)
    
    # Parallel loop over all keys
    for i in prange(n):
        if fast_check_pattern(public_keys[i], pattern):
            results[i] = 1
    
    return results

def batch_generate_keypairs(batch_size: int = 1000):
    """Generate multiple keypairs at once for better efficiency"""
    keypairs = []
    for _ in range(batch_size):
        signing_key = SigningKey.generate()
        secret_key = bytes(signing_key)
        verify_key = bytes(signing_key.verify_key)
        keypairs.append(secret_key + verify_key)
    return keypairs

def worker_process(pattern: str, found_key: Value, result_queue: Queue, total_attempts: Value):
    """Worker process to generate and check addresses in batches"""
    try:
        regex = re.compile(pattern)
        batch_size = 1000  # Adjust based on your CPU
        
        while not found_key.value:
            # Generate batch of keypairs
            keypairs = batch_generate_keypairs(batch_size)
            
            # Process in smaller chunks to avoid memory issues
            with total_attempts.get_lock():
                total_attempts.value += batch_size
            
            # Check each keypair in the batch
            for idx, keypair in enumerate(keypairs):
                public_key = keypair[32:]  # Last 32 bytes
                public_key_b58 = base58.b58encode(public_key).decode()
                
                if regex.search(public_key_b58):
                    with found_key.get_lock():
                        if not found_key.value:
                            found_key.value = True
                            result_queue.put(keypair)
                            return
                        
    except Exception as e:
        print(f"Worker error: {e}")

def generate_vanity_address(pattern: str, console: Console, test_mode: bool = False) -> None:
    """
    Generate a Solana address matching the specified regex pattern using multiple processes
    with JIT compilation and batch processing
    """
    try:
        re.compile(pattern)
    except re.error as e:
        console.print(f"[red]Invalid regex pattern: {str(e)}[/red]")
        return

    # Shared variables between processes
    found_key = Value(ctypes.c_bool, False)
    total_attempts = Value(ctypes.c_uint64, 0)
    result_queue = Queue()
    
    # Use all cores except one for system
    num_processes = 1 if test_mode else max(1, cpu_count() - 1)
    
    if not test_mode:
        console.print(f"\n[yellow]Starting {num_processes} optimized worker processes...[/yellow]")
        console.print("[yellow]Using JIT compilation and batch processing[/yellow]")
        console.print("[yellow]Press Ctrl+C to stop searching[/yellow]\n")
    
    # Start worker processes
    processes = []
    start_time = time.time()
    
    if not test_mode:
        # Warm up the JIT compiler
        console.print("[yellow]Warming up JIT compiler...[/yellow]")
        dummy_data = np.zeros((1, 32), dtype=np.uint8)
        dummy_pattern = np.zeros(1, dtype=np.uint8)
        parallel_check_keypairs(dummy_data, dummy_pattern)
    
    for _ in range(num_processes):
        p = Process(target=worker_process, args=(pattern, found_key, result_queue, total_attempts))
        p.start()
        processes.append(p)
    
    # Monitor progress and update display
    try:
        if test_mode:
            # In test mode, just wait for result
            while not found_key.value and result_queue.empty():
                time.sleep(0.1)
        else:
            with Live(console=console, refresh_per_second=4) as live:
                while not found_key.value:
                    elapsed = time.time() - start_time
                    attempts = total_attempts.value
                    rate = attempts / elapsed if elapsed > 0 else 0
                    
                    status = Panel(f"""[yellow]Searching with {num_processes} optimized processes:
Pattern: [magenta]{pattern}[/magenta]
Attempts: [blue]{attempts:,}[/blue]
Time: [blue]{elapsed:.2f}[/blue] seconds
Combined Rate: [blue]{rate:.0f}[/blue] addresses/second
Rate per core: [blue]{rate/num_processes:.0f}[/blue] addresses/second
Using: JIT compilation + Batch processing[/yellow]""")
                    
                    live.update(status)
                    time.sleep(0.25)
                    
                    if not result_queue.empty():
                        break
        
        # Get the result if found
        if not result_queue.empty():
            full_keypair = result_queue.get()
            # Split into private and public parts
            private_key = full_keypair[:32]  # First 32 bytes
            public_key = full_keypair[32:]   # Last 32 bytes
            
            # Convert to base58
            public_key_b58 = base58.b58encode(public_key).decode()
            # For Phantom wallet, we encode the full keypair
            private_key_b58 = base58.b58encode(full_keypair).decode()
            
            elapsed = time.time() - start_time
            attempts = total_attempts.value
            rate = attempts / elapsed if elapsed > 0 else 0
            
            match = re.search(pattern, public_key_b58)
            
            if test_mode:
                console.print(f"Public Key: {public_key_b58}")
                console.print(f"Private Key: {private_key_b58}")
            else:
                result = Panel(f"""[green]Found matching address![/green]
Public Key: [cyan]{public_key_b58}[/cyan]
Private Key (Phantom Compatible): [yellow]{private_key_b58}[/yellow]
Pattern: [magenta]{pattern}[/magenta]
Match Position: {match.start()}-{match.end()}
Attempts: [blue]{attempts:,}[/blue]
Time: [blue]{elapsed:.2f}[/blue] seconds
Combined Rate: [blue]{rate:.0f}[/blue] addresses/second
Rate per core: [blue]{rate/num_processes:.0f}[/blue] addresses/second

[green]✓ This private key can be imported directly into Phantom wallet[/green]""")
                
                # Also save to file
                with open("found_addresses.txt", "a") as f:
                    f.write(f"\nFound at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}:\n")
                    f.write(f"Public Key: {public_key_b58}\n")
                    f.write(f"Private Key: {private_key_b58}\n")
                    f.write("-" * 80 + "\n")
                
                console.print(result)
                console.print("\n[yellow]Address details have been saved to found_addresses.txt[/yellow]")
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Search cancelled by user[/yellow]")
    
    finally:
        # Cleanup: Set found flag and terminate all processes
        found_key.value = True
        for p in processes:
            p.terminate()
            p.join()

def main():
    import sys
    
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
        
    api = SolscanAPI()
    console = Console()
    
    option = sys.argv[1]
    
    if option == "-1":
        if len(sys.argv) != 3:
            print("Error: Address required for account balance")
            print_usage()
            sys.exit(1)
        address = sys.argv[2]
        balance = api.get_account_balance(address)
        if balance is not None:
            api.console.print(f"\nAccount Balance: [green]{balance:.9f}[/green] SOL")
        else:
            api.console.print("[red]Failed to fetch account balance[/red]")
            
    elif option == "-2":
        if len(sys.argv) != 3:
            print("Error: Address required for transaction history")
            print_usage()
            sys.exit(1)
        address = sys.argv[2]
        page_size = 10
        all_transactions = []
        page = 1
        max_transactions = 100
        
        api.console.print("\nFetching transactions...", style="yellow")
        
        while len(all_transactions) < max_transactions:
            transactions = api.get_account_transactions(address, page, page_size)
            if not transactions:
                break
            all_transactions.extend(transactions)
            if len(transactions) < page_size:
                break
            page += 1
        
        if all_transactions:
            api.console.print(f"\nFound [green]{len(all_transactions)}[/green] transactions\n")
            display_transactions_table(all_transactions, api.console, address)
        else:
            api.console.print("[red]Failed to fetch transactions or no transactions found[/red]")
            
    elif option == "-3":
        if len(sys.argv) != 3:
            print("Error: Address required for balance history")
            print_usage()
            sys.exit(1)
        address = sys.argv[2]
        api.console.print("\nFetching DEX trading history...", style="yellow")
        trades = api.get_dex_trading_history(address)
        
        if trades:
            api.console.print(f"\nFound [green]{len(trades)}[/green] DEX trades\n")
            display_dex_trading_summary(trades, api.console, address)
        else:
            api.console.print("[red]No DEX trading history found[/red]")
            
    elif option == "-4":
        if len(sys.argv) != 3:
            print("Error: Pattern required for vanity address")
            print_usage()
            sys.exit(1)
        pattern = sys.argv[2]
        if not pattern:
            console.print("[red]Pattern cannot be empty[/red]")
            sys.exit(1)
        generate_vanity_address(pattern, console)
        
    else:
        print(f"Error: Unknown option {option}")
        print_usage()
        sys.exit(1)

if __name__ == "__main__":
    main()
