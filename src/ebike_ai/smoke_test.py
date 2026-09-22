
import requests

# 服务器地址
BASE_URL = "http://127.0.0.1:8000"

# 健康检查
response = requests.get(f"{BASE_URL}/health")
assert response.status_code == 200

# 入参检查
resp = requests.post(f"{BASE_URL}/diagnose", json={"fault_text": ""})
assert resp.status_code == 422

print("冒烟测试通过 ✅")