from playwright.sync_api import sync_playwright
import yaml
import json
import os
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import re
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel, extra="allow"):
    payload: list[dict]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Set this to the origin(s) from which you want to allow requests, or use ["*"] to allow all origins.
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Set the HTTP methods you want to allow.
    allow_headers=["*"],  # Set the HTTP headers you want to allow.
)

BASE_URL = 'https://www.facebook.com'
settings_file_name = 'settings.yml'

with open(settings_file_name, 'r') as file:
    settings = yaml.safe_load(file)

# login to facebook
def login(page):
    page.goto(f'{BASE_URL}/login/device-based/regular/login/')
    page.wait_for_selector('input[name="email"]').fill(settings['email'])
    page.wait_for_selector('input[name="pass"]').fill(settings['password'])
    page.wait_for_selector('button[name="login"]').click()

    # There is a bug in playwright, have to manually wait till it's fixed: https://github.com/microsoft/playwright-python/issues/2238
    #page.wait_for_url(BASE_URL)
    page.wait_for_timeout(30000)

# scroll to the bottom of an infinite scroll
def scroll_to_bottom(page):
    prev_height = 0
    while prev_height != page.evaluate('(window.innerHeight + window.scrollY)'):
        prev_height = page.evaluate('(window.innerHeight + window.scrollY)')
        page.mouse.wheel(0, 150000)
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

def get_matching_posts(page):
    parsed = []
    soup = BeautifulSoup(page.content(), 'html.parser')

    # Iterate through all the listings and keep the ones that match the criteria
    listings = soup.find_all('div', class_='x9f619 x78zum5 x1r8uery xdt5ytf x1iyjqo2 xs83m0k x1e558r4 x150jy0e x1iorvi4 xjkvuk6 xnpuxes x291uyu x1uepa24')
    for listing in listings:
        try:
            image = listing.find('img', class_='xt7dq6l xl1xv1r x6ikm8r x10wlt62 xh8yej3')['src']
            title = listing.find('span', 'x1lliihq x6ikm8r x10wlt62 x1n2onr6').text
            price = listing.find('span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x xudqn12 x676frb x1lkfr7t x1lbecb7 x1s688f xzsf02u').text
            post_url = listing.find('a', class_='x1i10hfl xjbqb8w x1ejq31n xd10rxx x1sy0etr x17r0tee x972fbf xcfux6l x1qhh985 xm0m39n x9f619 x1ypdohk xt0psk2 xe8uvvx xdj266r x11i5rnm xat24cr x1mh8g0r xexx8yu x4uap5 x18d9i69 xkhd6sd x16tdsg8 x1hl2dhg xggy1nq x1a2a7pz x1heor9g x1lku1pv')['href']
            location = listing.find('span', 'x1lliihq x6ikm8r x10wlt62 x1n2onr6 xlyipyv xuxw1ft x1j85h84').text
            
            # keep the posts that match
            if all(string.lower() in title.lower() for string in settings['must-contain']) and all(string.lower() not in title.lower() for string in settings['dont-contain']):
                parsed.append({
                    'image': image,
                    'title': title,
                    'price': price,
                    'post_url': post_url,
                    'location': location
                })
        except Exception as e:
            print("something went wrong with extracting data from the listing:", e)

    return parsed

def pre_filter(posts):
    for post in posts:
        price = re.sub("[^0-9]", "", post['price'])
        if price == '' or int(price) <= 1234 or int(price) >= 100000:
            post['real'] = False
        else:
            post['real'] = True

@app.get('/')
def root():
    return {'message': 'temporary root message'}

@app.get("/scrape")
def get_basic_listings():
    """ with open('sample.json', 'r') as file:
        return json.load(file) """

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        login(page)

        posts = []
        for location in settings['locations']:
            for status in ['', 'availability=out of stock&']: # go through sold and non sold items
                
                # Go to the search page
                page.goto(f"{BASE_URL}/marketplace/{location}/search?{status}daysSinceListed={settings['days-since-listed']}&sortBy={settings['sort-by']}&query={settings['vehicle']}&exact=false&radius=805")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)

                # Load all the results
                scroll_to_bottom(page)
                page.wait_for_load_state("networkidle")

                # Get the results
                posts.extend(get_matching_posts(page))
        pre_filter(posts)

        # print results
        for x, post in enumerate(posts):
            print(x, post)
        print('count', len(posts))

        return posts
    
@app.post("/archive")
def archive_listings(item: Item):
    # TODO archive the posts
    print(item.payload)
    return {'response': 'temp'}

if __name__ == '__main__':
    uvicorn.run(
        'app:app',
        host='127.0.0.1',
        port=8000
    )