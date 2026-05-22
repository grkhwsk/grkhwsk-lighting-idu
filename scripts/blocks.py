import geopandas as gpd
import pandas as pd

blocks = gpd.read_file('data/interim/blocks_v5.gpkg')
zones = gpd.read_file('data/processed/zones.gpkg', layer='zone').to_crs('EPSG:32645')
ni_s0 = gpd.read_file('data/scenarios/NI_midseason_evening_no_snow_scenario_1.gpkg')
print('Колонки ni_s0:', ni_s0.columns.tolist())  # ← добавьте эту строку

scenarios = {
    'S0_midseason_evening':       'data/scenarios/NI_midseason_evening_no_snow_scenario_1.gpkg',
    'S1_midseason_morning':       'data/scenarios/NI_midseason_morning_no_snow_scenario_1.gpkg',
    'S1_midseason_day':           'data/scenarios/NI_midseason_day_no_snow_scenario_1.gpkg',
    'S1_midseason_night':         'data/scenarios/NI_midseason_night_no_snow_scenario_1.gpkg',
    'S2_winter_evening':          'data/scenarios/NI_winter_evening_no_snow_scenario_1.gpkg',
    'S2_summer_evening':          'data/scenarios/NI_summer_evening_no_snow_scenario_1.gpkg',
    'S3_midseason_evening_dirty': 'data/scenarios/NI_midseason_evening_dirty_snow_scenario_1.gpkg',
    'S3_midseason_evening_clean': 'data/scenarios/NI_midseason_evening_clean_snow_scenario_1.gpkg',
    'S0_midseason_evening_sc2':   'data/scenarios/NI_midseason_evening_no_snow_scenario_2.gpkg',
    'S0_midseason_evening_sc3':   'data/scenarios/NI_midseason_evening_no_snow_scenario_3.gpkg',
}

# Зона по центроиду
centroids = blocks.copy()
centroids['geometry'] = centroids.geometry.centroid
joined = gpd.sjoin(centroids[['block_id','area_m2','perimeter','geometry']],
                   zones[['zone_group','zone_code','geometry']],
                   how='left', predicate='within')
joined['zone_group'] = joined['zone_group'].fillna('Outside')
result = joined[['block_id','area_m2','zone_group','zone_code']].copy()

# NeedIndex по сценариям
for label, path in scenarios.items():
    ni = gpd.read_file(path)
    ni_in = gpd.sjoin(ni[['NeedIndex','geometry']],
                      blocks[['block_id','geometry']],
                      how='left', predicate='within')
    stats = ni_in.groupby('block_id').agg(
        ni_mean=('NeedIndex','mean'),
        active_pct=('NeedIndex', lambda x: round((x>0).sum()/len(x)*100,1))
    ).reset_index()
    stats.columns = ['block_id', f'ni_{label}', f'pct_{label}']
    result = result.merge(stats, on='block_id', how='left')

# % покрытия маской S0 (независимо от слота)
grid_s0 = gpd.read_file('data/interim/grid_s0_1.gpkg')
mask_in = gpd.sjoin(grid_s0[['Mask_S0','geometry']],
                    blocks[['block_id','geometry']],
                    how='left', predicate='within')
mask_stats = mask_in.groupby('block_id').agg(
    mask_pct=('Mask_S0', lambda x: round(x.sum()/len(x)*100, 1))
).reset_index()
result = result.merge(mask_stats, on='block_id', how='left')
result['mask_pct'] = result['mask_pct'].fillna(0)

    # pct_24h — доля ячеек mask_24h = 1 в квартале
ni_s0 = gpd.read_file('data/scenarios/NI_midseason_evening_no_snow_scenario_1.gpkg')

if 'mask_24h' in ni_s0.columns:
    ni_24h = gpd.sjoin(ni_s0[['mask_24h','geometry']],
                       blocks[['block_id','geometry']],
                       how='left', predicate='within')
    stats_24h = ni_24h.groupby('block_id').agg(
        pct_24h=('mask_24h', lambda x: round(x.sum()/len(x)*100, 1))
    ).reset_index()
    result = result.merge(stats_24h, on='block_id', how='left')
    result['pct_24h'] = result['pct_24h'].fillna(0)
    print('\nТоп кварталов по pct_24h:')
    print(result.nlargest(5,'pct_24h')[['block_id','zone_group','pct_24h','ni_S0_midseason_evening']].to_string())

# POI по кварталам
poly = gpd.read_file('data/interim/poi_polygons_merged_refactor_clean_with_ranks.gpkg')
pts  = gpd.read_file('data/interim/poi_point_merged_refactor_clean_without_doubles__With_ranks.gpkg')
pts['spatial_role'] = 'facility'

poi_all = pd.concat([
    poly[['activity_type','rank','geometry']],
    pts[['activity_type','rank','geometry']]
]).pipe(gpd.GeoDataFrame, crs=poly.crs).to_crs('EPSG:32645')

# Только rank 1
poi_r1 = poi_all[poi_all['rank'] == 1].copy()
poi_r1['geometry'] = poi_r1.geometry.centroid

poi_in_blocks = gpd.sjoin(poi_r1[['activity_type','geometry']],
                           blocks[['block_id','geometry']],
                           how='left', predicate='within')

# Общее число POI rank 1 на квартал
poi_count = poi_in_blocks.groupby('block_id').agg(
    poi_count=('activity_type','count'),
    dominant_type=('activity_type', lambda x: x.value_counts().index[0])
).reset_index()

# Разбивка по типам активности (через pivot)
poi_pivot = poi_in_blocks.groupby(['block_id','activity_type']).size().unstack(fill_value=0)
poi_pivot.columns = [f'poi_{c}' for c in poi_pivot.columns]
poi_pivot = poi_pivot.reset_index()

result = result.merge(poi_count, on='block_id', how='left')
result = result.merge(poi_pivot, on='block_id', how='left')
result['poi_count'] = result['poi_count'].fillna(0).astype(int)
result['dominant_type'] = result['dominant_type'].fillna('—')

# Округляем ni_
for col in result.columns:
    if col.startswith('ni_'):
        result[col] = result[col].round(3)

result_gdf = gpd.GeoDataFrame(
    result,
    geometry=blocks.set_index('block_id').loc[result['block_id'].values, 'geometry'].values,
    crs='EPSG:32645'
)
result_gdf.to_file('data/interim/blocks_final.gpkg', driver='GPKG')

print('По зонам (S0):')
print(result_gdf.groupby('zone_group').agg(
    кварталов=('block_id','count'),
    ni_S0=('ni_S0_midseason_evening', lambda x: round(x.mean(),3)),
    ni_зима=('ni_S2_winter_evening', lambda x: round(x.mean(),3)),
    poi_avg=('poi_count', lambda x: round(x.mean(),1)),
    площадь_км2=('area_m2', lambda x: round(x.sum()/1e6,2))
).to_string())

print('\nТоп кварталов по POI rank 1:')
print(result_gdf.nlargest(10,'poi_count')[
    ['block_id','zone_group','poi_count','dominant_type',
     'ni_S0_midseason_evening']
].to_string())

print('\nСохранено: data/interim/blocks_final.gpkg')