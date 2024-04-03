import yaml

settings_file_name = 'settings.yml'

with open(settings_file_name, 'r') as file:
    settings = yaml.safe_load(file)