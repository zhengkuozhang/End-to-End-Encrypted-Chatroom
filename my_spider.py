import requests
from bs4 import BeautifulSoup
import csv
import time
import random

def scrape_books_data():
    # 1. 目标网址 (Target URL)
    url = "http://books.toscrape.com/"
    
    # 2. 请求头伪装 (Request Headers)
    # 告诉服务器：“我不是代码，我是 Windows 电脑上的 Chrome 浏览器”
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print("开始抓取数据 (Start scraping)...")
    
    try:
        # 3. 发送带伪装的请求，并设置超时时间 (Timeout) 为 10 秒
        response = requests.get(url, headers=headers, timeout=10)
        
        # 检查状态码，如果不是 200 (成功)，则抛出异常
        response.raise_for_status() 
        
        # 4. 解析网页 (Parse HTML)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 5. 提取数据 (Data Extraction) - 使用 CSS 选择器
        # 找到所有代表一本书的 <article> 标签，它的 class 是 'product_pod'
        books = soup.select("article.product_pod")
        
        # 准备一个列表，用来装提取好的数据
        book_data_list = []
        
        for book in books:
            # 提取书名：在 <h3> 标签下的 <a> 标签里的 title 属性
            title = book.select_one("h3 a")["title"]
            # 提取价格：在 class 为 'price_color' 的 <p> 标签里
            price = book.select_one("p.price_color").text
            
            # 把书名和价格组合成字典，存入列表
            book_data_list.append({"Title": title, "Price": price})
            
        # 6. 数据持久化 (Data Persistence) - 保存为 CSV 文件
        # 使用 'w' 模式打开文件，newline='' 防止 Windows 下产生多余空行
        with open("books_data.csv", mode="w", encoding="utf-8-sig", newline="") as file:
            # 定义表头列名
            writer = csv.DictWriter(file, fieldnames=["Title", "Price"])
            writer.writeheader() # 写入表头
            writer.writerows(book_data_list) # 批量写入所有数据行
            
        print(f"成功抓取 {len(book_data_list)} 本书的数据，已保存至 books_data.csv！")
        
        # 7. 礼貌性延迟 (Polite Delay) - 随机休息 1 到 3 秒
        time.sleep(random.uniform(1, 3))
        
    except requests.exceptions.RequestException as e:
        # 捕获所有网络相关的错误 (如断网、超时、服务器拒绝)
        print(f"网络请求出错 (Network Error): {e}")

# 运行主函数
if __name__ == "__main__":
    scrape_books_data()