from flask import Flask, render_template, request, jsonify, session
import requests
import hashlib
import time
import urllib.parse
import re
import json
import os
from functools import wraps, reduce

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

CONFIG_FILE = 'config.json'

# WBI签名相关
mixinKeyEncTab = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

def getMixinKey(orig: str):
    """对 imgKey 和 subKey 进行字符顺序打乱编码"""
    return reduce(lambda s, i: s + orig[i], mixinKeyEncTab, '')[:32]

def encWbi(params: dict, img_key: str, sub_key: str):
    """为请求参数进行 wbi 签名"""
    mixin_key = getMixinKey(img_key + sub_key)
    curr_time = round(time.time())
    params['wts'] = curr_time
    params = dict(sorted(params.items()))
    params = {
        k: ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params['w_rid'] = wbi_sign
    return params

class BilibiliAPI:
    def __init__(self, sessdata, bili_jct, buvid3):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.buvid3 = buvid3
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com',
            'Origin': 'https://www.bilibili.com',
            'Cookie': f'SESSDATA={sessdata}; bili_jct={bili_jct}; buvid3={buvid3}'
        }
        self.img_key = None
        self.sub_key = None
        self._get_wbi_keys()
    
    def get_video_info(self, bvid):
        """获取视频信息"""
        url = f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'
        try:
            resp = requests.get(url, headers=self.headers)
            data = resp.json()
            if data['code'] == 0:
                return data['data']
            else:
                print(f"获取视频信息失败: code={data['code']}, message={data.get('message')}")
            return None
        except Exception as e:
            print(f"获取视频信息异常: {e}")
            return None
    
    def like_video(self, bvid):
        """点赞视频"""
        url = 'https://api.bilibili.com/x/web-interface/archive/like'
        data = {
            'bvid': bvid,
            'like': 1,
            'csrf': self.bili_jct
        }
        try:
            resp = requests.post(url, data=data, headers=self.headers)
            result = resp.json()
            if result['code'] != 0:
                print(f"点赞失败: {result}")
            return result
        except Exception as e:
            print(f"点赞异常: {e}")
            return {'code': -1, 'message': str(e)}
    
    def coin_video(self, bvid, num=1):
        """投币"""
        url = 'https://api.bilibili.com/x/web-interface/coin/add'
        data = {
            'bvid': bvid,
            'multiply': num,
            'select_like': 0,
            'csrf': self.bili_jct
        }
        try:
            resp = requests.post(url, data=data, headers=self.headers)
            result = resp.json()
            if result['code'] != 0:
                print(f"投币失败: {result}")
            return result
        except Exception as e:
            print(f"投币异常: {e}")
            return {'code': -1, 'message': str(e)}
    
    def favorite_video(self, bvid, add_media_ids):
        """收藏视频"""
        video_info = self.get_video_info(bvid)
        if not video_info:
            return {'code': -1, 'message': '获取视频信息失败'}
        
        aid = video_info['aid']
        url = 'https://api.bilibili.com/x/v3/fav/resource/deal'
        data = {
            'rid': aid,
            'type': 2,
            'add_media_ids': str(add_media_ids),
            'del_media_ids': '',
            'csrf': self.bili_jct
        }
        try:
            resp = requests.post(url, data=data, headers=self.headers)
            result = resp.json()
            if result['code'] != 0:
                print(f"收藏失败: aid={aid}, fav_id={add_media_ids}, result={result}")
            return result
        except Exception as e:
            print(f"收藏异常: {e}")
            return {'code': -1, 'message': str(e)}
    
    def get_user_videos(self, mid, page=1, page_size=50):
        """获取用户的视频列表"""
        # 使用WBI签名的API
        url = 'https://api.bilibili.com/x/space/wbi/arc/search'
        params = {
            'mid': mid,
            'ps': page_size,
            'pn': page,
            'order': 'pubdate',
            'platform': 'web',
            'web_location': '1550101',
            'order_avoided': 'true'
        }
        
        try:
            # 如果有WBI密钥，进行签名
            if self.img_key and self.sub_key:
                signed_params = encWbi(params.copy(), self.img_key, self.sub_key)
                print(f"使用WBI签名请求用户 {mid} 的视频")
                resp = requests.get(url, params=signed_params, headers=self.headers, timeout=10)
            else:
                print(f"WBI密钥未获取，使用普通请求")
                resp = requests.get(url, params=params, headers=self.headers, timeout=10)
            
            data = resp.json()
            print(f"获取用户视频API返回: code={data.get('code')}, message={data.get('message')}")
            
            if data['code'] == 0:
                if data.get('data') and data['data'].get('list') and data['data']['list'].get('vlist'):
                    videos = data['data']['list']['vlist']
                    print(f"成功获取 {len(videos)} 个视频")
                    return videos
                else:
                    print("API返回成功但没有视频数据")
                    return []
            else:
                print(f"API返回错误: {data}")
            
            # 如果WBI接口失败，尝试使用旧接口
            print("尝试使用备用API...")
            url2 = 'https://api.bilibili.com/x/space/arc/search'
            params2 = {
                'mid': mid,
                'ps': page_size,
                'pn': page,
                'order': 'pubdate'
            }
            resp2 = requests.get(url2, params=params2, headers=self.headers, timeout=10)
            data2 = resp2.json()
            print(f"备用API返回: code={data2.get('code')}, message={data2.get('message')}")
            
            if data2['code'] == 0 and data2.get('data') and data2['data'].get('list'):
                videos = data2['data']['list'].get('vlist', [])
                print(f"备用API成功获取 {len(videos)} 个视频")
                return videos
            
            return []
        except Exception as e:
            print(f"获取用户视频异常: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_favorite_folders(self):
        """获取收藏夹列表"""
        url = 'https://api.bilibili.com/x/v3/fav/folder/created/list-all'
        params = {
            'up_mid': self.get_my_uid()
        }
        try:
            resp = requests.get(url, params=params, headers=self.headers)
            data = resp.json()
            if data['code'] == 0 and data['data']:
                return data['data']['list']
            return []
        except Exception as e:
            print(f"获取收藏夹失败: {e}")
            return []
    
    def get_my_uid(self):
        """获取当前登录用户的UID"""
        url = 'https://api.bilibili.com/x/web-interface/nav'
        try:
            resp = requests.get(url, headers=self.headers)
            data = resp.json()
            if data['code'] == 0:
                return data['data']['mid']
            return None
        except Exception as e:
            print(f"获取用户信息失败: {e}")
            return None
    
    def _get_wbi_keys(self):
        """获取最新的 img_key 和 sub_key"""
        try:
            resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=self.headers)
            data = resp.json()
            if data['code'] == 0:
                wbi_img = data['data']['wbi_img']
                img_url = wbi_img['img_url']
                sub_url = wbi_img['sub_url']
                self.img_key = img_url.rsplit('/', 1)[1].split('.')[0]
                self.sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
                print(f"获取WBI密钥成功: img_key={self.img_key[:8]}..., sub_key={self.sub_key[:8]}...")
            else:
                print(f"获取WBI密钥失败: {data}")
        except Exception as e:
            print(f"获取WBI密钥异常: {e}")

def extract_bvid(url):
    """从URL中提取BV号"""
    patterns = [
        r'BV[a-zA-Z0-9]+',
        r'bilibili\.com/video/(BV[a-zA-Z0-9]+)',
        r'b23\.tv/([a-zA-Z0-9]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            bvid = match.group(1) if 'bilibili.com' in pattern else match.group(0)
            if bvid.startswith('BV'):
                return bvid
    return None

def extract_mid(url):
    """从URL中提取用户ID"""
    # 如果直接输入的是数字，直接返回
    if url.strip().isdigit():
        return url.strip()
    
    patterns = [
        r'space\.bilibili\.com/(\d+)',
        r'bilibili\.com/(\d+)',
        r'mid[=:](\d+)',
        r'/(\d+)/?$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            mid = match.group(1)
            print(f"从URL '{url}' 提取到用户ID: {mid}")
            return mid
    
    print(f"无法从 '{url}' 提取用户ID")
    return None

def save_config(sessdata, bili_jct, buvid3):
    """保存配置到文件"""
    config = {
        'sessdata': sessdata,
        'bili_jct': bili_jct,
        'buvid3': buvid3
    }
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False

def load_config():
    """从文件加载配置"""
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"加载配置失败: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/load_config', methods=['GET'])
def load_saved_config():
    """加载保存的配置"""
    config = load_config()
    if config:
        return jsonify({'success': True, 'config': config})
    return jsonify({'success': False, 'message': '没有保存的配置'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    sessdata = data.get('sessdata')
    bili_jct = data.get('bili_jct')
    buvid3 = data.get('buvid3')
    
    if not all([sessdata, bili_jct, buvid3]):
        return jsonify({'success': False, 'message': '请填写完整的登录信息'})
    
    # 验证登录信息
    api = BilibiliAPI(sessdata, bili_jct, buvid3)
    uid = api.get_my_uid()
    
    if uid:
        session['sessdata'] = sessdata
        session['bili_jct'] = bili_jct
        session['buvid3'] = buvid3
        
        # 保存配置到文件
        save_config(sessdata, bili_jct, buvid3)
        
        # 获取收藏夹列表
        folders = api.get_favorite_folders()
        return jsonify({'success': True, 'message': '登录成功', 'folders': folders})
    else:
        return jsonify({'success': False, 'message': '登录信息无效，请检查Cookie是否正确'})

@app.route('/api/get_folders', methods=['GET'])
def get_folders():
    if 'sessdata' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    api = BilibiliAPI(session['sessdata'], session['bili_jct'], session['buvid3'])
    folders = api.get_favorite_folders()
    return jsonify({'success': True, 'folders': folders})

@app.route('/api/triple', methods=['POST'])
def triple():
    if 'sessdata' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    data = request.json
    urls = data.get('urls', [])
    actions = data.get('actions', {})
    
    api = BilibiliAPI(session['sessdata'], session['bili_jct'], session['buvid3'])
    results = []
    
    for url in urls:
        bvid = extract_bvid(url)
        if not bvid:
            results.append({'url': url, 'success': False, 'message': '无效的视频链接'})
            continue
        
        result = {'url': url, 'bvid': bvid, 'success': True, 'details': {}}
        
        # 点赞
        if actions.get('like', False):
            like_result = api.like_video(bvid)
            result['details']['like'] = {
                'success': like_result['code'] == 0,
                'message': like_result.get('message', '成功' if like_result['code'] == 0 else '失败')
            }
            time.sleep(0.5)
        
        # 投币
        if actions.get('coin', False):
            coin_num = actions.get('coin_num', 1)
            coin_result = api.coin_video(bvid, coin_num)
            result['details']['coin'] = {
                'success': coin_result['code'] == 0,
                'message': coin_result.get('message', '成功' if coin_result['code'] == 0 else '失败'),
                'num': coin_num
            }
            time.sleep(0.5)
        
        # 收藏
        if actions.get('favorite', False):
            fav_id = actions.get('favorite_id', '')
            if fav_id:
                fav_result = api.favorite_video(bvid, fav_id)
                result['details']['favorite'] = {
                    'success': fav_result['code'] == 0,
                    'message': fav_result.get('message', '成功' if fav_result['code'] == 0 else '失败'),
                    'code': fav_result.get('code')
                }
                time.sleep(0.5)
            else:
                result['details']['favorite'] = {
                    'success': False,
                    'message': '未选择收藏夹'
                }
        
        results.append(result)
    
    return jsonify({'success': True, 'results': results})

@app.route('/api/user_videos', methods=['POST'])
def user_videos():
    if 'sessdata' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    data = request.json
    user_url = data.get('user_url', '')
    
    if not user_url:
        return jsonify({'success': False, 'message': '请输入用户链接或UID'})
    
    mid = extract_mid(user_url)
    if not mid:
        return jsonify({'success': False, 'message': '无效的用户链接或UID，请输入正确的格式（如：https://space.bilibili.com/123456 或直接输入 123456）'})
    
    print(f"正在获取用户 {mid} 的视频列表...")
    api = BilibiliAPI(session['sessdata'], session['bili_jct'], session['buvid3'])
    videos = api.get_user_videos(mid)
    
    if not videos:
        return jsonify({'success': False, 'message': f'未找到用户 {mid} 的视频，请检查UID是否正确或该用户是否有公开视频'})
    
    video_list = [{'bvid': v['bvid'], 'title': v['title'], 'pic': v.get('pic', '')} for v in videos]
    
    return jsonify({'success': True, 'videos': video_list, 'mid': mid})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
