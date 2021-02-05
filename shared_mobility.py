import requests
from datetime import datetime
import psycopg2
import sys
from yaml import load, FullLoader
from argparse import ArgumentParser

def get_data(args):

    config_file = args.filename

    with open(config_file) as file:
        params = load(file, Loader=FullLoader)

    bbox = params['bbox']
    connection_params = params['connection_params']
    providers_info_url = params['providers_info_url']
    station_info_url = params['station_info_url']
    station_status_url = params['station_status_url']
    tablename = params['tablename']

    connection = psycopg2.connect(
        host = connection_params['host'],
        database = connection_params['db'],
        user = connection_params['user'],
        password = connection_params['password']
    )

    cursor= connection.cursor()

    # Get Stations
    r = requests.get(station_info_url)

    if r.status_code != 200:
        sys.exit(1)

    stations = r.json()['data']['stations']

    station_ids = []

    station_sql = """
    INSERT INTO %s (idobj, "name", provider_id, geom) VALUES ('%s', '%s', '%s', %s) ON CONFLICT DO NOTHING
    """

    for station in stations:
        if station['lon'] >= bbox['xmin'] and station['lon'] <= bbox['xmax'] \
            and station['lat'] >= bbox['ymin'] and station ['lat'] <= bbox['ymax']:
                station_ids.append(station['station_id'])
                cursor.execute(station_sql % (
                    tablename,
                    station['station_id'], 
                    station['name'].replace("'", "''"), 
                    station['provider_id'],
                    "ST_Transform(ST_GeomFromText('POINT("+ str(station['lon']) + " " + str(station['lat']) +")', 4326), 2056)"
                ))

    connection.commit()

    # Check uris
    url_sql = """
    SELECT provider_id FROM %s WHERE provider_url is null
    """
    cursor.execute(url_sql % (tablename))
    records = cursor.fetchall()

    update_urls_sql = """
    UPDATE %s SET 
        provider_url = '%s',  
        store_uri_android = '%s',
        store_uri_ios = '%s'
    WHERE
        provider_id = '%s'
    """

    if len(records) > 0:
        r = requests.get(providers_info_url)

        if r.status_code != 200:
            sys.exit(1)

        providers = r.json()['data']['providers']
        done = []

        for record in records:
            
            if record[0] not in done:
                provider = list(filter(lambda x:x["provider_id"]==record[0], providers))
                if len(provider) == 0:
                    continue
                provider = provider[0]
                cursor.execute(update_urls_sql % (
                    tablename,
                    provider['url'] if 'url' in provider else '-9999',
                    provider['rental_apps']['android']['store_uri'] if 'rental_apps' in provider else '-9999',
                    provider['rental_apps']['ios']['store_uri'] if 'rental_apps' in provider else '-9999',
                    record[0], 
                ))
                
                done.append(record[0])
        
        connection.commit()

    # Check vehicle availability
    r = requests.get(station_status_url)

    if r.status_code != 200:
        sys.exit(1)

    stations = r.json()['data']['stations']

    station_sql = """
    UPDATE %s SET 
        is_installed = %s,  
        is_renting = %s,
        is_returning = %s,
        last_reported = '%s', 
        num_bikes_available = %s,
        num_docks_available = %s,
        update_time = '%s'
    WHERE
        idobj = '%s'
    """

    now = datetime.now().isoformat()

    for station_id in station_ids:
        station = list(filter(lambda x:x["station_id"]==station_id,stations))
        
        if len(station) == 0:
            continue
        
        station = station[0]
        
        cursor.execute(station_sql % (
            tablename,
            str(station['is_installed']), 
            str(station['is_renting']),
            str(station['is_returning']),
            datetime.fromtimestamp(station['last_reported']).isoformat(),
            str(station['num_bikes_available']),
            str(station['num_docks_available']),
            now,
            station['station_id'], 
        ))

    connection.commit()

    cursor.close()
    connection.close()

if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        '-f',
        '--filename',
        help='filename of the config file (optional, default would be config.yml)',
        default='config.yml',
        action='store'
    )
    args = parser.parse_args()

    get_data(args)
