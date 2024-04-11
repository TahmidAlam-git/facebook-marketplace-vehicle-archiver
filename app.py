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

def soup_find(soup: BeautifulSoup, type: str, class_name: str):
    if soup == None:
        return ''
    res = soup.find(type, class_=class_name)
    return res.text if res != None else ''

def get_post_details(page):

    result = {'description': '', 'title': '', 'year': '', 'price': '', 'date': '', 'location': '', 'mileage': '', 'color': '', 'seller': '', 'images': [], 'sold': False}

    # open the full description
    description_button = page.get_by_role("button", name="See more")
    if description_button.is_visible():
        description_button.click()
        page.wait_for_timeout(500)

    soup = BeautifulSoup(page.content(), 'html.parser')

    # get description
    result['description'] = soup_find(soup, 'div', 'xz9dl7a x4uap5 xsag5q8 xkhd6sd x126k92a')

    # get title
    header = soup.find('div', class_='xyamay9 x1pi30zi x18d9i69 x1swvt13')
    result['title'] = soup_find(header, 'span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x x14z4hjw x3x7a5m xngnso2 x1qb5hxa x1xlr1w8 xzsf02u')

    # get model year
    year = re.search(r'(\d\d\d\d)', result['title'])
    result['year'] = year.group(1) if year else ''

    # Sold status
    result['sold'] = 'sold' in result['title'].lower() or 'pending' in result['title'].lower()

    # get price
    result['price'] = soup_find(header, 'span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x xudqn12 x676frb x1lkfr7t x1lbecb7 x1s688f xzsf02u')
    if result['price'] == '':
        price = soup_find(header, 'span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x xudqn12 x676frb x1lkfr7t x1lbecb7 xk50ysn xzsf02u')
        price = re.search(r'\$(\d+(,\d+)?)', price)
        result['price'] = price.group(1) if price else ''

    # get date
    result['date'] = soup_find(header, 'span', 'html-span xdj266r x11i5rnm xat24cr x1mh8g0r xexx8yu x4uap5 x18d9i69 xkhd6sd x1hl2dhg x16tdsg8 x1vvkbs')
    
    # get location
    result['location'] = soup_find(header, 'span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1nxh6w3 x1sibtaa xo1l8bm xi81zsa')

    spans = soup.find_all('span', class_='x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x xudqn12 x3x7a5m x6prxxf xvq8zen xo1l8bm xzsf02u')
    if len(spans) > 0:
        # get mileage
        mileage = [span for span in spans if 'Driven' in span.text]
        mileage = mileage[0].text if len(mileage) > 0 else ''
        mileage = re.search(r'Driven (\d+(,\d+)?) miles', mileage)
        result['mileage'] = mileage.group(1) if mileage else ''

        # get color
        color = [span for span in spans if 'color' in span.text]
        color = color[0].text if len(color) > 0 else ''
        color = re.search(r'Exterior color: (\w+) ?\w*', color)
        result['color'] = color.group(1) if color else ''

    # get seller name
    header = soup.find('div', class_='x1lq5wgf xgqcy7u x30kzoy x9jhf4c x1lliihq')
    if header:
        result['seller'] = soup_find(header, 'span', 'x193iq5w xeuugli x13faqbe x1vvkbs x1xmvt09 x6prxxf xvq8zen x1s688f xzsf02u')

    # get images
    image_roll = soup.find('div', class_='x6s0dn4 x78zum5 x193iq5w x1y1aw1k xwib8y2 xu6gjpd x11xpdln x1r7x56h xuxw1ft xc9qbxq')
    if image_roll:
        result['images'] = [image['src'] for image in image_roll.find_all('img', class_='x5yr21d xl1xv1r xh8yej3')]
    else:
        image = soup.find('img', class_='xz74otr')
        result['images'] = [image['src']] if image else []

    return result

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
    """ with open('sample2.json', 'r') as file:
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
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        login(page)

        for listing in item.payload:
            if not listing['real']:
                continue

            # go to the listing page
            page.goto(f"{BASE_URL}{listing['post_url']}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            # save the listing if not already saved
            button = page.get_by_role('button', name="Save", pressed=False)
            if button.is_visible():
                button.click()
                print('saved', listing['post_url'])
            else:
                print('already saved', listing['post_url'])

            print(get_post_details(page))
        
        browser.close()

    return {'response': 'temp'}

if __name__ == '__main__':
    uvicorn.run(
        'app:app',
        host='127.0.0.1',
        port=8000
    )