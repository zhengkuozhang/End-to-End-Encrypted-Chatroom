import socket
import threading
import struct
import time
import queue
import os
import sqlite3
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
from cryptography.fernet import Fernet

# ================= 1. 全局配置 =================
SECRET_KEY = b'MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI='
cipher = Fernet(SECRET_KEY)
MAGIC_WORD = b"P2P_CHAT_NODE_V2" # 升级了暗号版本
UDP_PORT = 9999
TCP_PORT = 8888
DOWNLOAD_DIR = "P2P_Downloads" # 接收到的文件统一存放在这里

# 确保下载文件夹存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

MY_IP = get_local_ip()

# ================= 2. 数据库管理 =================
def init_db():
    """初始化 SQLite 本地数据库"""
    conn = sqlite3.connect('chat_history.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sender TEXT,
                  msg_type TEXT,
                  content TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

db_conn = init_db()

def save_message_to_db(sender, msg_type, content):
    """保存消息到数据库"""
    c = db_conn.cursor()
    c.execute("INSERT INTO messages (sender, msg_type, content) VALUES (?, ?, ?)", 
              (sender, msg_type, content))
    db_conn.commit()

# ================= 3. 升级版底层协议 =================
def recv_all(sock, length):
    data = b''
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet: return None
        data += packet
    return data

def recv_raw(sock):
    """只负责接收并解密成原始字节 (不管它是文字还是文件)"""
    header = recv_all(sock, 4)
    if not header: return None
    msg_len = struct.unpack('!I', header)[0]
    encrypted_bytes = recv_all(sock, msg_len)
    if not encrypted_bytes: return None
    try:
        return cipher.decrypt(encrypted_bytes)
    except Exception:
        return None

def send_raw(sock, raw_bytes):
    """负责加密原始字节并打包发送"""
    encrypted_bytes = cipher.encrypt(raw_bytes)
    header = struct.pack('!I', len(encrypted_bytes))
    sock.sendall(header + encrypted_bytes)

# ================= 4. 核心应用类 =================
class P2PChatNode:
    def __init__(self, root):
        self.root = root
        self.root.title(f"究极加密 P2P 聊天室 - (我的IP: {MY_IP})")
        self.root.geometry("500x600")
        
        self.peers = {} 
        self.msg_queue = queue.Queue()

        self.setup_ui()
        self.load_history() # 启动时加载历史记录
        self.start_network_engines()

    def setup_ui(self):
        # 聊天显示区
        self.chat_area = scrolledtext.ScrolledText(self.root, state='disabled', wrap=tk.WORD, font=("微软雅黑", 10))
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # 底部操作区
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=10)

        self.msg_entry = tk.Entry(bottom_frame, font=("微软雅黑", 12))
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.msg_entry.bind("<Return>", lambda e: self.send_text_message())

        # 新增：发送文件按钮
        self.file_btn = tk.Button(bottom_frame, text="📁 传文件", command=self.send_file_message, bg="#f39c12", fg="white")
        self.file_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.send_btn = tk.Button(bottom_frame, text="发送", command=self.send_text_message, bg="#008CBA", fg="white")
        self.send_btn.pack(side=tk.RIGHT)

    def load_history(self):
        """从 SQLite 加载历史聊天记录"""
        c = db_conn.cursor()
        c.execute("SELECT sender, msg_type, content, timestamp FROM messages ORDER BY id ASC")
        rows = c.fetchall()
        if rows:
            self.display_system_message("--- 以下为本地加密的历史记录 ---")
            for row in rows:
                sender, msg_type, content, time_str = row
                if msg_type == 'text':
                    self.display_chat_message(sender, content, time_str)
                elif msg_type == 'file':
                    self.display_chat_message(sender, f"[文件] {content}", time_str)
            self.display_system_message("--- 历史记录加载完毕 ---")

    def start_network_engines(self):
        threading.Thread(target=self.tcp_server_thread, daemon=True).start()
        threading.Thread(target=self.udp_listen_thread, daemon=True).start()
        threading.Thread(target=self.udp_broadcast_thread, daemon=True).start()
        self.root.after(100, self.process_queue)

    # ---------------- 网络通讯逻辑 ----------------
    def tcp_server_thread(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('0.0.0.0', TCP_PORT))
        server.listen(5)
        while True:
            conn, addr = server.accept()
            peer_ip = addr[0]
            if peer_ip not in self.peers:
                self.peers[peer_ip] = conn
                self.msg_queue.put(("system", f"节点 [{peer_ip}] 接入。"))
                threading.Thread(target=self.tcp_receive_worker, args=(conn, peer_ip), daemon=True).start()

    def udp_listen_thread(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('', UDP_PORT))
        while True:
            try:
                data, addr = listener.recvfrom(1024)
                peer_ip = addr[0]
                if data == MAGIC_WORD and peer_ip != MY_IP and peer_ip not in self.peers:
                    self.connect_to_peer(peer_ip)
            except Exception:
                pass

    def udp_broadcast_thread(self):
        broadcaster = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcaster.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                broadcaster.sendto(MAGIC_WORD, ('<broadcast>', UDP_PORT))
            except Exception:
                pass
            time.sleep(3)

    def connect_to_peer(self, peer_ip):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((peer_ip, TCP_PORT))
            self.peers[peer_ip] = client
            self.msg_queue.put(("system", f"已连接至节点 [{peer_ip}]。"))
            threading.Thread(target=self.tcp_receive_worker, args=(client, peer_ip), daemon=True).start()
        except Exception:
            pass

    def tcp_receive_worker(self, sock, peer_ip):
        """【核心】带类型区分的接收逻辑"""
        while True:
            try:
                raw_bytes = recv_raw(sock)
                if not raw_bytes: break
                
                # 判断第一个字节是 T(文本) 还是 F(文件)
                if raw_bytes.startswith(b'T'):
                    text = raw_bytes[1:].decode('utf-8')
                    self.msg_queue.put((peer_ip, "text", text))
                    save_message_to_db(peer_ip, "text", text) # 保存到数据库
                    
                elif raw_bytes.startswith(b'F'):
                    # 以 b'::' 为界限，拆分文件名和文件内容
                    parts = raw_bytes[1:].split(b'::', 1)
                    if len(parts) == 2:
                        filename = parts[0].decode('utf-8')
                        file_data = parts[1]
                        
                        # 写入到本地下载文件夹
                        save_path = os.path.join(DOWNLOAD_DIR, f"{peer_ip}_{filename}")
                        with open(save_path, 'wb') as f:
                            f.write(file_data)
                            
                        notice = f"已接收文件并保存在: {save_path}"
                        self.msg_queue.put((peer_ip, "file", notice))
                        save_message_to_db(peer_ip, "file", filename)
            except Exception as e:
                break
                
        sock.close()
        if peer_ip in self.peers:
            del self.peers[peer_ip]

    # ---------------- 界面交互与发送逻辑 ----------------
    def send_text_message(self):
        msg = self.msg_entry.get()
        if not msg.strip(): return
        self.msg_entry.delete(0, tk.END)
        
        self.display_chat_message("我", msg)
        save_message_to_db("我", "text", msg) # 存入数据库
        
        payload = b'T' + msg.encode('utf-8')
        self._broadcast_to_peers(payload)

    def send_file_message(self):
        """打开文件选择器并发送文件"""
        filepath = filedialog.askopenfilename()
        if not filepath: return
        
        filename = os.path.basename(filepath)
        
        try:
            # 读取文件二进制内容 (注意：此MVP不适用于GB级别的超大文件，因为会全部读入内存)
            with open(filepath, 'rb') as f:
                file_data = f.read()
                
            self.display_chat_message("我", f"[发送了文件] {filename}")
            save_message_to_db("我", "file", filename)
            
            # 打包协议: b'F' + 文件名字节 + b'::' + 文件数据
            payload = b'F' + filename.encode('utf-8') + b'::' + file_data
            
            # 使用子线程发送，防止文件太大导致界面卡住
            threading.Thread(target=self._broadcast_to_peers, args=(payload,), daemon=True).start()
        except Exception as e:
            messagebox.showerror("错误", f"无法读取文件: {e}")

    def _broadcast_to_peers(self, payload):
        """将打包好的数据群发给所有人"""
        for ip, sock in list(self.peers.items()):
            try:
                send_raw(sock, payload)
            except Exception:
                pass

    def process_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                if len(item) == 2:
                    # 系统消息
                    self.display_system_message(item[1])
                else:
                    # 聊天消息: (sender, type, content)
                    sender, msg_type, content = item
                    self.display_chat_message(sender, content)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)

    def display_system_message(self, text):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"⚠️ {text}\n", "system")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def display_chat_message(self, sender, text, time_str=None):
        if time_str:
            display_text = f"[{time_str}] [{sender}]: {text}\n"
        else:
            time_str = time.strftime("%Y-%m-%d %H:%M:%S")
            display_text = f"[{time_str}] [{sender}]: {text}\n"
            
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, display_text)
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = P2PChatNode(root)
    root.mainloop()