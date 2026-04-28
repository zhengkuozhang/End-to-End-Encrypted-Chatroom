import socket
import threading
import struct
import time
import queue
import tkinter as tk
from tkinter import scrolledtext
from tkinter.simpledialog import askstring
import ipaddress
from cryptography.fernet import Fernet

# ================= 1. 全局配置与加密模块 =================
SECRET_KEY = b'MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI='
cipher = Fernet(SECRET_KEY)
MAGIC_WORD = b"P2P_CHAT_NODE_V1"
UDP_PORT = 9999
TCP_PORT = 8888


def get_local_ip():
    """获取本机的真实局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


MY_IP = get_local_ip()


# ================= 2. 底层安全通信协议 (Header + Body) =================
def recv_all(sock, length):
    data = b''
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return data


def recv_msg(sock):
    header = recv_all(sock, 4)
    if not header:
        return None
    msg_len = struct.unpack('!I', header)[0]
    encrypted_bytes = recv_all(sock, msg_len)
    if not encrypted_bytes:
        return None
    try:
        return cipher.decrypt(encrypted_bytes).decode('utf-8')
    except Exception:
        return "[解密失败] 收到非法数据"


def send_msg(sock, msg):
    encrypted_bytes = cipher.encrypt(msg.encode('utf-8'))
    header = struct.pack('!I', len(encrypted_bytes))
    sock.sendall(header + encrypted_bytes)


# ================= 3. 核心应用类 (面向对象架构) =================
class P2PChatNode:
    def __init__(self, root):
        self.root = root
        self.peers = {}                    # ip -> socket
        self.peer_nicknames = {}           # ip -> 昵称
        self.msg_queue = queue.Queue()

        self.setup_ui()
        self.start_network_engines()

    def setup_ui(self):
        """绘制前端 GUI 界面"""
        self.chat_area = scrolledtext.ScrolledText(self.root, state='disabled', wrap=tk.WORD)
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # 配置消息样式
        self.chat_area.tag_configure("system", foreground="#666666", font=("Arial", 10, "italic"))
        self.chat_area.tag_configure("me", foreground="#008CBA", font=("Arial", 11, "bold"))

        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=10)

        self.msg_entry = tk.Entry(bottom_frame, font=("Arial", 12))
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.msg_entry.bind("<Return>", lambda e: self.send_message())

        self.send_btn = tk.Button(bottom_frame, text="发送加密消息", command=self.send_message,
                                  bg="#008CBA", fg="white")
        self.send_btn.pack(side=tk.RIGHT)

    def start_network_engines(self):
        """启动后台四大并发引擎"""
        self.display_system_message("系统初始化，生成端到端加密密钥...")
        self.display_system_message(f"本地 IP: {MY_IP}，开始扫描局域网节点...")

        # 1. TCP 服务端
        threading.Thread(target=self.tcp_server_thread, daemon=True).start()
        # 2. UDP 监听雷达
        threading.Thread(target=self.udp_listen_thread, daemon=True).start()
        # 3. UDP 广播
        threading.Thread(target=self.udp_broadcast_thread, daemon=True).start()
        # 4. GUI 消息队列处理
        self.root.after(100, self.process_queue)

    # ---------------- 核心网络逻辑 ----------------
    def tcp_server_thread(self):
        """引擎1：TCP 服务端"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('0.0.0.0', TCP_PORT))
        server.listen(5)
        while True:
            try:
                conn, addr = server.accept()
                peer_ip = addr[0]
                if peer_ip not in self.peers:
                    self.peers[peer_ip] = conn
                    self.msg_queue.put(("system", f"节点 [{peer_ip}] 已接入加密网络。"))
                    threading.Thread(target=self.tcp_receive_worker,
                                   args=(conn, peer_ip), daemon=True).start()
                    # 连接成功后立即交换昵称
                    try:
                        send_msg(conn, f"__NICK__:{self.my_username}")
                    except Exception:
                        pass
            except Exception:
                pass

    def udp_listen_thread(self):
        """引擎2：UDP 雷达 + 智能防重复连接"""
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('', UDP_PORT))
        while True:
            try:
                data, addr = listener.recvfrom(1024)
                peer_ip = addr[0]
                if (data == MAGIC_WORD and
                    peer_ip != MY_IP and
                    peer_ip not in self.peers):
                    # 只有 IP 更大的节点主动发起连接，避免重复 TCP
                    if ipaddress.ip_address(MY_IP) > ipaddress.ip_address(peer_ip):
                        self.connect_to_peer(peer_ip)
            except Exception:
                pass

    def udp_broadcast_thread(self):
        """引擎3：UDP 广播"""
        broadcaster = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcaster.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                broadcaster.sendto(MAGIC_WORD, ('<broadcast>', UDP_PORT))
            except Exception:
                pass
            time.sleep(3)

    def connect_to_peer(self, peer_ip):
        """主动连接"""
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((peer_ip, TCP_PORT))
            self.peers[peer_ip] = client
            self.msg_queue.put(("system", f"已成功连接到节点 [{peer_ip}]。"))
            threading.Thread(target=self.tcp_receive_worker,
                            args=(client, peer_ip), daemon=True).start()
            # 连接成功后立即交换昵称
            try:
                send_msg(client, f"__NICK__:{self.my_username}")
            except Exception:
                pass
        except Exception:
            pass

    def tcp_receive_worker(self, sock, peer_ip):
        """专职接收线程"""
        while True:
            try:
                msg = recv_msg(sock)
                if not msg:
                    break

                # 处理昵称交换（特殊协议消息）
                if msg.startswith("__NICK__:"):
                    nick = msg[len("__NICK__:"):].strip()
                    if peer_ip not in self.peer_nicknames or self.peer_nicknames[peer_ip] != nick:
                        self.peer_nicknames[peer_ip] = nick
                        self.msg_queue.put(("system", f"[{peer_ip}] 的昵称已更新为: {nick}"))
                    continue

                # 普通聊天消息
                self.msg_queue.put((peer_ip, msg))
            except Exception:
                break

        # 连接断开清理
        sock.close()
        if peer_ip in self.peers:
            del self.peers[peer_ip]
        if peer_ip in self.peer_nicknames:
            del self.peer_nicknames[peer_ip]
        self.msg_queue.put(("system", f"节点 [{peer_ip}] 离开了网络。"))

    # ---------------- 界面交互逻辑 ----------------
    def send_message(self):
        """发送消息（群发）"""
        msg = self.msg_entry.get().strip()
        if not msg:
            return

        self.msg_entry.delete(0, tk.END)
        self.display_chat_message(None, msg, is_me=True)

        for ip, sock in list(self.peers.items()):
            try:
                send_msg(sock, msg)
            except Exception:
                pass  # 由接收线程负责清理

    def process_queue(self):
        """主线程刷新 UI"""
        try:
            while True:
                msg_type, msg_content = self.msg_queue.get_nowait()
                if msg_type == "system":
                    self.display_system_message(msg_content)
                else:
                    self.display_chat_message(msg_type, msg_content, is_me=False)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)

    def display_system_message(self, text):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"⚠️ {text}\n", "system")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def display_chat_message(self, sender_ip, text, is_me=False):
        self.chat_area.config(state='normal')
        if is_me:
            display_sender = self.my_username
            tag = "me"
            prefix = f"[{display_sender} (我)]: "
        else:
            nick = self.peer_nicknames.get(sender_ip, sender_ip)
            display_sender = nick
            tag = None
            prefix = f"[{display_sender}]: "
        self.chat_area.insert(tk.END, prefix + text + "\n", tag)
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    # 启动前弹出昵称输入框
    app = P2PChatNode(root)
    # 在 __init__ 里已经设置了 title，这里无需重复
    root.mainloop()