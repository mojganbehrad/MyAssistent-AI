import requests
user_input = input("what do you want to add ?")

response = requests.post(
     "http://localhost:11434/api/generate",
     json={
         "model":"llama3.2",
         "prompt":user_input,
         "stream":False
     }
)

print(response.json()["response"])