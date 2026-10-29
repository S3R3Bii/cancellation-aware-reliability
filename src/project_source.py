"""Project the hash-pinned official export; raw archives remain outside this repository."""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['year','month','carrier','airport','arr_flights','arr_del15','arr_cancelled','arr_diverted']
COUNTS = FIELDS[4:]

def write_json(path, data):
    path.write_bytes((json.dumps(data,indent=2,sort_keys=True)+'\n').encode())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--archive',required=True,type=Path)
    args=ap.parse_args()
    assert not args.archive.resolve().is_relative_to(ROOT), 'Keep complete source archives outside the public repository'
    cfg=json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    raw=args.archive.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==cfg['source']['zip_sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert [n for n in z.namelist() if n.lower().endswith('.csv')]==['Airline_Delay_Cause.csv']
        data=z.read('Airline_Delay_Cause.csv')
    assert hashlib.sha256(data).hexdigest()==cfg['source']['csv_sha256']
    rows=[]
    with io.TextIOWrapper(io.BytesIO(data),encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        assert set(FIELDS)<=set(reader.fieldnames)
        for source in reader:
            row={}
            for key in FIELDS:
                value=source[key].strip()
                if key in ['carrier','airport']:
                    assert re.fullmatch('[A-Z0-9]{2,3}',value), key
                    row[key]=value
                elif value=='':row[key]=None
                else:
                    dec=Decimal(value)
                    assert dec.is_finite() and dec==dec.to_integral_value() and dec>=0,key
                    row[key]=int(dec)
            assert row['year'] in range(2019,2026) and row['month'] in range(1,13)
            if row['arr_flights'] and any(row[k] is None for k in COUNTS):
                identified = (row['arr_del15'] is None and
                              all(row[k] is not None for k in ['arr_flights','arr_cancelled','arr_diverted']) and
                              row['arr_flights']==row['arr_cancelled']+row['arr_diverted'])
                assert identified, 'Positive remaining denominator with unknown outcome counts'
            if all(row[k] is not None for k in COUNTS):
                assert row['arr_del15']+row['arr_cancelled']+row['arr_diverted']<=row['arr_flights']
            rows.append(row)
    key=lambda x:(x['year'],x['month'],x['carrier'],x['airport'])
    assert len({key(r) for r in rows})==len(rows), 'Duplicate full source keys'
    assert {(r['year'],r['month']) for r in rows}=={(y,m) for y in range(2019,2026) for m in range(1,13)}
    rows.sort(key=key)

    # C-parser numeric conversion and ordering are independent of Decimal/DictReader.
    frame=pd.read_csv(io.BytesIO(data),usecols=FIELDS,dtype={'carrier':'string','airport':'string'},engine='c')
    assert len(frame)==len(rows)
    for column in FIELDS[:2]+COUNTS:
        series=pd.to_numeric(frame[column],errors='raise')
        assert ((series.dropna()%1)==0).all() and (series.dropna()>=0).all()
        frame[column]=series.astype('Int64')
    frame=frame.sort_values(['year','month','carrier','airport'])
    independent=frame[FIELDS].itertuples(index=False,name=None)
    checks=0
    for row, other in zip(rows,independent):
        for field,value in zip(FIELDS,other):
            actual=None if pd.isna(value) else str(value) if field in ['carrier','airport'] else int(value)
            assert row[field]==actual,(key(row),field)
            checks+=1

    totals={c:sum(r[c] or 0 for r in rows) for c in COUNTS}
    actual=dict(N=totals['arr_flights'],C=totals['arr_cancelled'],V=totals['arr_diverted'])
    actual['O']=actual['N']-totals['arr_del15']-actual['C']-actual['V']
    control=json.loads((ROOT/'data/source/control_totals.json').read_text(encoding='utf-8'))
    assert actual==control['counts'], (actual,control['counts'])
    for name,value in actual.items():
        basis_points=Fraction(value*10000,actual['N'])
        rounded=(basis_points.numerator*2//basis_points.denominator+1)//2
        assert f'{rounded/100:.2f}'==control['display_percent'][name]
    selected=[r for r in rows if r['carrier'] in cfg['carriers']]
    assert {r['carrier'] for r in selected}==set(cfg['carriers'])
    output=io.StringIO(newline='')
    writer=csv.DictWriter(output,fieldnames=FIELDS,lineterminator='\n');writer.writeheader();writer.writerows(selected)
    projection=output.getvalue().encode('utf-8')
    target=ROOT/'data/source/flight-counts.csv.gz'
    target.write_bytes(gzip.compress(projection,mtime=0))
    quality=dict(source_rows=len(rows),selected_rows=len(selected),source_months=84,source_key='year/month/carrier/airport',duplicate_keys=0,
                 null_count_fields={c:sum(r[c] is None for r in rows) for c in COUNTS},zero_scheduled_rows=sum(r['arr_flights']==0 for r in rows),
                 selected_null_count_fields={c:sum(r[c] is None for r in selected) for c in COUNTS},selected_zero_scheduled_rows=sum(r['arr_flights']==0 for r in selected),
                 logically_zero_delay_with_original_null=sum(r['arr_del15'] is None and all(r[k] is not None for k in ['arr_flights','arr_cancelled','arr_diverted']) and r['arr_flights']==r['arr_cancelled']+r['arr_diverted'] for r in rows),
                 null_resolution='Original null retained. Exact nonnegative partition bound identifies D=O=0 only at N=C+V. Conditional B=0 rates remain undefined.')
    manifest=dict(source_landing=cfg['source']['landing'],source_zip_sha256=cfg['source']['zip_sha256'],source_csv_sha256=cfg['source']['csv_sha256'],
                  source_zip_bytes=len(raw),source_csv_bytes=len(data),projection_file='data/source/flight-counts.csv.gz',projection_csv_sha256=hashlib.sha256(projection).hexdigest(),
                  projection_gzip_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),fields=FIELDS,quality=quality,
                  actual_full_export_controls=actual,source_control_checks=8,independent_parser_scalar_checks=checks,
                  interpretation='Captured reported nominal carrier/airport count cells, not independently verified unique flights, passenger truth or historical publication vintages.',
                  rights=cfg['source']['rights'],raw_source_public=False)
    write_json(ROOT/'data/source/manifest.json',manifest)
    print(json.dumps(dict(status='PASS',**quality,independent_parser_scalar_checks=checks,source_control_checks=8)))

if __name__=='__main__':main()
