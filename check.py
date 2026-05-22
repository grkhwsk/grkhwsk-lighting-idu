import geopandas as gpd
grid = gpd.read_file(r'cities/polyarnye_zori/data/generated/grid_s0.gpkg')

# Сколько ячеек с active_night=1 среди тех, что в маске
mask = grid[grid['Mask_S0'] == 1]
print('active_night в маске:')
print(mask['active_night'].value_counts())

# Для сравнения
print('\nactive_evening в маске:')
print(mask['active_evening'].value_counts())