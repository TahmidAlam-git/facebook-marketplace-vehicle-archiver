from playwright.sync_api import sync_playwright
import yaml
import json
import os

BASE_URL = 'https://www.facebook.com'
auth_file_name = 'auth.json'
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
    page.wait_for_timeout(20000)

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        login(page)

        page.goto('https://www.facebook.com/marketplace/you/saved')
        page.wait_for_timeout(60000)

if __name__ == '__main__':
    main()