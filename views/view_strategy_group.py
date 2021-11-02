# 目前市面上各种策略(高收益, 双低, 活性债, 回售)的数据视图展示


# 需导入要用到的库文件
import json

from prettytable import from_db_cursor

import utils.table_html_utils
import utils.trade_utils
from models import db, Config
from utils import html_utils
from utils.db_utils import get_record, get_cursor
from utils.echarts_html_utils import generate_scatter_html_with_multi_tables
from views import view_strategy_group_yield

strategy_list = ['双低策略',
                 # '低价格策略',
                 # '低余额+双低策略',
                 '低溢价率策略',
                 '高收益率策略']


def get_strategy_yield_rate():
    dates = get_dates(strategy_list)
    create_date_s = dates['双低策略']
    table = get_double_low_strategy_table(create_date_s)
    double_low_strategy_rate = get_yield_rate_of_strategy(table)

    create_date_s = dates['高收益率策略']
    table = get_high_yield_strategy_table(create_date_s)
    high_yield_strategy_rate = get_yield_rate_of_strategy(table)

    create_date_s = dates['低溢价率策略']
    table = get_low_premium_strategy_table(create_date_s)
    low_premium_strategy_rate = get_yield_rate_of_strategy(table)

    return double_low_strategy_rate, high_yield_strategy_rate, low_premium_strategy_rate

def draw_view(user_id):
    use_personal_features = user_id is not None

    html = ''

    nav_html_list = ['<li><a href="/">Home</a></li>']
    tables = {}
    try:
        # fixme 暂时不支持轮动可转债个数不足10个的情况, 这样会导致逻辑变的非常复杂
        # 用上一个交易日作为条件
        dates = get_dates(strategy_list)
        # =========双低债=========
        strategy_name = '双低策略'
        if strategy_name in strategy_list:
            create_date_s = dates[strategy_name]
            table = get_double_low_strategy_table(create_date_s)
            html = generate_strategy_table_html("双低策略", table, html, tables, nav_html_list,
                                                use_personal_features=use_personal_features)
        # =========高收益策略=========
        strategy_name = '高收益率策略'
        if strategy_name in strategy_list:
            create_date_s = dates[strategy_name]
            table = get_high_yield_strategy_table(create_date_s)
            html = generate_strategy_table_html("高收益率策略", table, html, tables, nav_html_list,
                                                use_personal_features=use_personal_features)

        # =========低溢价率策略=========
        strategy_name = '低溢价率策略'
        if strategy_name in strategy_list:
            create_date_s = dates[strategy_name]
            table = get_low_premium_strategy_table(create_date_s)
            html = generate_strategy_table_html("低溢价率策略", table, html, tables, nav_html_list,
                                                use_personal_features=use_personal_features)

        # =========低余额策略=========
        if "低余额+双低策略" in strategy_list:
            # 双低
            html = build_low_remain_block(html, nav_html_list, 'cb_price2_id+cb_premium_id*100', '双低', tables,
                                      use_personal_features)

        # =========低价格策略=========
        if "低价格策略" in strategy_list:
            sql = """
        SELECT DISTINCT d.* , e.hold_id, e.hold_amount as 持有数量
  FROM (
      SELECT c.data_id as nid, c.bond_code, c.stock_code, c.cb_name_id as 名称, 
        cb_price2_id as '转债价格', round(cb_premium_id*100,2) || '%' as 溢价率--,round(cb_price2_id + cb_premium_id * 100, 2) as 双低值
        , round(bt_yield*100,2) || '%' as 到期收益率,
        round(cb_mov2_id * 100, 2) || '%' as 可转债涨跌, round(cb_mov_id * 100, 2) || '%' as 正股涨跌,round(cb_trade_amount2_id * 100,2) || '%' as '换手率(%)', 
        c.stock_name as 正股名称, c.industry as '行业', c.sub_industry as '子行业', e.theme as 题材概念,
         
        rank_gross_rate ||'【' || level_gross_rate || '】' as 毛利率排名,rank_net_margin ||'【' || level_net_margin || '】' as 净利润排名,
        rank_net_profit_ratio ||'【' || level_net_profit_ratio || '】'  as 利润率排名, rank_roe ||'【' || level_roe || '】' as ROE排名,
        rank_pe ||'【' || level_pe || '】' as PE排名, rank_pb ||'【' || level_pb || '】' as PB排名,
        rank_net_asset ||'【' || level_net_asset || '】' as 净资产排名, rank_market_cap ||'【' || level_market_cap || '】' as 市值排名,
        stock_total as 综合评分, 
        
        round(s.revenue,2) as '营收(亿元)',s.yoy_revenue_rate || '%' as '营收同比',
        gross_rate||'|' || avg_gross_rate as '毛利率|行业均值',  
        round(s.net,2)||'|' || avg_net_margin as '净利润|均值(亿元)', s.yoy_net_rate || '%' as '净利润同比', 
        s.margin ||'|' || avg_net_profit_ratio as '利润率|行业均值', s.yoy_margin_rate || '%' as '利润率同比', 
        s.roe ||'|' || avg_roe as 'ROE|行业均值', s.yoy_roe_rate || '%' as 'ROE同比', 
        round(s.al_ratio,2) || '%' as 负债率, s.yoy_al_ratio_rate || '%' as '负债率同比', 
        s.pe||'|' || avg_pe as 'PE(动)|均值',  
        c.stock_pb||'|' || avg_pb as 'PB|行业均值', 
        net_asset||'|' || avg_net_asset as '净资产|行业均值', 
        market_cap||'|' || avg_market_cap as '市值|均值(亿元)', 
        remain_amount as '余额(亿元)', round(cb_to_share_shares * 100,2) || '%'  as '余额/股本(%)',
                
        fact_trend || '|' || fact_money || '|' || fact_news || '|' || fact_industry || '|' || fact_base as '技术|资金|消息|行业|基本面',  
        trade_suggest as 操作建议,
        
        rating as '信用', duration as 续存期, cb_ma20_deviate as 'ma20乖离', cb_hot as 热门度, cb_trade_amount_id as '成交额(百万)', 
        e.interest as 各期利息, case when e.ensure is not null then  '有' else  '无' END as 担保, case when e.buy_back_term is not null then  e.buy_back_term else  '无' END as 回售条款, 
        case when e.down_revise_term is not null then  e.down_revise_term else  '无' END as 下修条款, case when e.enforce_get_term is not null then  e.enforce_get_term else  '无' END as 强赎条款 
  
        from (changed_bond_view c left join stock_report s on c.stock_code = s.stock_code)
                  left join changed_bond_extend e on c.bond_code = e.bond_code
        ORDER by cb_price2_id
        limit 10) d left join 
            (select id as hold_id, bond_code, cb_name_id, hold_price, hold_amount 
                from hold_bond 
                where strategy_type='低价格策略轮动'
            ) e 
        on d.bond_code = e.bond_code
        
            """
            html = generate_strategy_table_html(sql, "低价格策略", "低价格前10", html, tables, nav_html_list=nav_html_list,
                                                use_personal_features=use_personal_features)


        scatter_html = generate_scatter_html_with_multi_tables(tables, title="组合策略可转债分布情况", subtitle='每种策略选取top10, 按日/周/月轮动', use_personal_features=use_personal_features)

        html = """
                    <br/>
                    <br/>
                    <br/>
                    <br/>
                    <br/>
                    <center>
                        """ + scatter_html + "<br/><br/>" + """
                    </center>
                """ + html

        html_utils.add_nav_html(nav_html_list, '策略组合收益率')
        html += "<div id='策略组合收益率'>" + view_strategy_group_yield.draw_view() + "</div>"

        return '策略组合轮动', ''.join(nav_html_list), html

    except Exception as e:
        print("processing is failure. " + str(e), e)
        raise e


def get_low_premium_strategy_table(create_date_s):
    sql = """
        SELECT DISTINCT d.*, e.hold_id, e.hold_amount as 持有数量
        FROM (
                 SELECT data_id                              as nid,
                        bond_code,
                        stock_code,
                        cb_name_id                           as 名称,
                        sort_num,
                        cur_sort                             as 排序,
                        rotate                               as 轮动,
                        round(cb_premium_id * 100, 2) || '%' as 溢价率,
                        round(cb_mov2_id * 100, 2) || '%'    as 可转债涨跌,
                        cb_price2_id                         as '转债价格',
                        round(cb_mov_id * 100, 2) || '%'     as 正股涨跌,
                        round(bt_yield * 100, 2) || '%'      as 到期收益率,
                        stock_name                           as 正股名称,
                        industry                             as '行业',
                        sub_industry                         as '子行业'
                 from (select *
                       from (select f.*, case when sort_num is NULL then '轮入' else '持有' end as rotate
                             from (select d.*,
                                          (select count(*)
                                           from (select cb_premium_id as sort_value
                                                 from changed_bond_view
                                                 order by cb_premium_id
                                                 limit 10) e
                                           where d.sort_value >= e.sort_value) as cur_sort
                                   from (select c.*
                                         from (select a.*,
                                                      date()                 as create_date,
                                                      strftime('%s', date()) as create_date_s,
                                                      ''                     as strategy_name,
                                                      b.sort_num,
                                                      a.cb_premium_id        as sort_value
                                               from (select * from changed_bond_view order by cb_premium_id limit 10) a
                                                        left join (select *
                                                                   from changed_bond_top_history
                                                                   where strategy_name = '低溢价率策略'
                                                                     and create_date_s = :create_date_s) b on a.id = b.id
                                              ) c) d) f
                             UNION
                             select d.*,
                                    ''              as create_date,
                                    ''              as create_date_s,
                                    ''              as strategy_name,
                                    c.sort_num,
                                    d.cb_premium_id as sort_value,
                                    ''              as cur_sort,
                                    '轮出'            as rotate
                             from changed_bond_view d
                                      inner join (select b.*
                                                  from changed_bond_top_history b
                                                           left join (select *
                                                                      from changed_bond_view
                                                                      order by cb_premium_id
                                                                      limit 10) a on b.id = a.id
                                                  where b.strategy_name = '低溢价率策略'
                                                    and a.id is NULL
                                                    and create_date_s = :create_date_s) c
                                                 on d.id = c.id)
                       order by sort_value)
             ) d
                 left join
             (select id as hold_id, bond_code, cb_name_id, hold_price, hold_amount
              from hold_bond
                 --where strategy_type = '低溢价率策略轮动'
             ) e
             on d.bond_code = e.bond_code
                  """
    return get_table(sql, {'create_date_s': create_date_s})


def get_high_yield_strategy_table(create_date_s):
    sql = """
        SELECT DISTINCT d.*, e.hold_id, e.hold_amount as 持有数量
        FROM (
                 SELECT data_id                              as nid,
                        bond_code,
                        stock_code,
                        cb_name_id                           as 名称,
                        sort_num,
                        cur_sort                             as 排序,
                        rotate                               as 轮动,
                        round(bt_yield * 100, 2) || '%'      as 到期收益率,
                        round(cb_mov2_id * 100, 2) || '%'    as 可转债涨跌,
                        cb_price2_id                         as '转债价格',
                        round(cb_premium_id * 100, 2) || '%' as 溢价率,
                        round(cb_mov_id * 100, 2) || '%'     as 正股涨跌,
                        stock_name                           as 正股名称,
                        industry                             as '行业',
                        sub_industry                         as '子行业'
                 from (select *
                       from (select f.*, case when sort_num is NULL then '轮入' else '持有' end as rotate
                             from (select d.*,
                                          (select count(*)
                                           from (select bt_yield as sort_value
                                                 from changed_bond_view
                                                 order by bt_yield desc
                                                 limit 10) e
                                           where d.sort_value <= e.sort_value) as cur_sort
                                   from (select c.*
                                         from (select a.*,
                                                      date()                 as create_date,
                                                      strftime('%s', date()) as create_date_s,
                                                      ''                     as strategy_name,
                                                      b.sort_num,
                                                      a.bt_yield             as sort_value
                                               from (select * from changed_bond_view order by bt_yield desc limit 10) a
                                                        left join (select *
                                                                   from changed_bond_top_history
                                                                   where strategy_name = '高收益率策略'
                                                                     and create_date_s = :create_date_s) b on a.id = b.id
                                              ) c) d) f
                             UNION
                             select d.*,
                                    ''         as create_date,
                                    ''         as create_date_s,
                                    ''         as strategy_name,
                                    c.sort_num,
                                    d.bt_yield as sort_value,
                                    ''         as cur_sort,
                                    '轮出'       as rotate
                             from changed_bond_view d
                                      inner join (select b.*
                                                  from changed_bond_top_history b
                                                           left join (select *
                                                                      from changed_bond_view
                                                                      order by bt_yield desc
                                                                      limit 10) a on b.id = a.id
                                                  where b.strategy_name = '高收益率策略'
                                                    and a.id is NULL
                                                    and create_date_s = :create_date_s) c
                                                 on d.id = c.id)
                       order by sort_value desc)
             ) d
                 left join
             (select id as hold_id, bond_code, cb_name_id, hold_price, hold_amount
              from hold_bond
                 --where strategy_type = '高收益率策略轮动'
             ) e
             on d.bond_code = e.bond_code
            """
    return get_table(sql, {'create_date_s': create_date_s})


def get_double_low_strategy_table(create_date_s):
    sql = """
        SELECT DISTINCT d.*, e.hold_id, e.hold_amount as 持有数量
        FROM (
                 SELECT data_id                                      as nid,
                        bond_code,
                        stock_code,
                        cb_name_id                                   as 名称,
                        sort_num,
                        cur_sort                                     as 排序,
                        rotate                                       as 轮动,
                        round(cb_price2_id + cb_premium_id * 100, 2) as 双低值,
                        round(cb_mov2_id * 100, 2) || '%'            as 可转债涨跌,
                        cb_price2_id                                 as '转债价格',
                        round(cb_premium_id * 100, 2) || '%'         as 溢价率,
                        round(bt_yield * 100, 2) || '%'              as 到期收益率,
                        round(cb_mov_id * 100, 2) || '%'             as 正股涨跌,
                        stock_name                                   as 正股名称,
                        industry                                     as '行业',
                        sub_industry                                 as '子行业'
                 from (select *
                       from (select f.*, case when sort_num is NULL then '轮入' else '持有' end as rotate
                             from (select d.*,
                                          (select count(*)
                                           from (select cb_price2_id + cb_premium_id * 100 as sort_value
                                                 from changed_bond_view
                                                 order by cb_price2_id + cb_premium_id * 100
                                                 limit 10) e
                                           where d.sort_value >= e.sort_value) as cur_sort
                                   from (select a.*,
                                                date()                                 as create_date,
                                                strftime('%s', date())                 as create_date_s,
                                                ''                                     as strategy_name,
                                                b.sort_num,
                                                a.cb_price2_id + a.cb_premium_id * 100 as sort_value
                                         from (select *
                                               from changed_bond_view
                                               order by cb_price2_id + cb_premium_id * 100
                                               limit 10) a
                                                  left join (select *
                                                             from changed_bond_top_history
                                                             where strategy_name = '双低策略'
                                                               and create_date_s = :create_date_s) b on a.id = b.id
                                        ) d) f
                             UNION
                             select d.*,
                                    ''                                     as create_date,
                                    ''                                     as create_date_s,
                                    ''                                     as strategy_name,
                                    c.sort_num,
                                    d.cb_price2_id + d.cb_premium_id * 100 as sort_value,
                                    ''                                     as cur_sort,
                                    '轮出'                                   as rotate
                             from changed_bond_view d
                                      inner join (select b.*
                                                  from changed_bond_top_history b
                                                           left join (select *
                                                                      from changed_bond_view
                                                                      order by cb_price2_id + cb_premium_id * 100
                                                                      limit 10) a on b.id = a.id
                                                  where b.strategy_name = '双低策略'
                                                    and a.id is NULL
                                                    and create_date_s = :create_date_s) c
                                                 on d.id = c.id)
                       order by sort_value)
             ) d
                 left join
             (select id as hold_id, bond_code, cb_name_id, hold_price, hold_amount
              from hold_bond
                 --where strategy_type = '双低策略轮动'
             ) e
             on d.bond_code = e.bond_code
            """
    return get_table(sql, {'create_date_s': create_date_s})


def get_dates(strategy_list):
    cursor = get_cursor("""
        select strategy_name, max(create_date_s) 
        from changed_bond_top_history 
        where create_date_s < strftime('%s', date()) 
        group by strategy_name
        """)
    rows = cursor.fetchall()
    dates = {}
    for row in rows:
        for s in strategy_list:
            if row[0] == s:
                dates[s] = row[1]
                break
    return dates


def get_strategy_list():
    row = db.session.query(Config).filter(
        Config.group == 'public_strategy_type_list', Config.key == 'strategy_type', Config.is_delete == 0).first()
    strategy_list = json.loads(row.value)
    return strategy_list


def generate_strategy_table_html(type, table, html, tables,
                                 nav_html_list=None, remark_fields=['轮动'],
                                 use_personal_features=False):

    if len(table._rows) == 0:
        return html

    if tables is not None:
        tables[type] = table

    yield_rate = get_yield_rate_of_strategy(table)

    scatter_html = '当日涨跌: ' + str(yield_rate) + '%<br/>'

    html_utils.add_nav_html(nav_html_list, type)

    # 把排序字段补齐
    i = 1
    for row in table._rows:
        row[5] = i
        m = row[4]
        if m is None or m == '':
            m = 11
        delta = m - i
        arrow = " (<font style='color: green; '>⬇</font>︎" + str(abs(delta)) + ")"
        if delta > 0:
            arrow = " (<font style='color: red; '>⬆︎</font>︎" + str(abs(delta)) + ')'
        elif delta == 0:
            arrow = ''
        row[5] = str(i) + arrow

        i += 1

    html += """
    <div id=\"""" + type + """\">
        """ + "</br></br><center>=========<font size=4><b>" + type + "</b></font>=========</center>"\
            + scatter_html \
            + utils.table_html_utils.build_table_html(table, remark_fields,
                                                      remark_strategy_1=lambda name, value: (name == '轮动' and value == '轮入') or value.startswith('-'),
                                                      remark_strategy_2=lambda name, value: (name == '轮动' and value == '轮出') or (name != '轮动'),
                                                      ignore_fields=['持有数量', 'sort_num'],
                                                      is_login_user=use_personal_features,
                                                      table_rows_size=6) + """
    </div>
    """

    return html


def get_table(sql, params):
    cur = db.session.execute(sql, params)
    return from_db_cursor(cur.cursor)


def get_yield_rate_of_strategy(table):
    # 采用加权方式计算组合当前涨跌(收益率)
    rate_value = 0
    cost = 0
    for row in table._rows:
        record = get_record(table, row)
        rotate = record.get('轮动')
        price = float(record.get('转债价格'))
        rate = float(record.get('可转债涨跌').replace('%', '')) / 100
        cost += price / (1 + rate)
        # 当前被轮动轮入的可转债不计算收益
        if rotate != '轮入':
            rate_value += price / (1 + rate) * rate
    yield_rate = round(rate_value / cost * 100, 2)
    return yield_rate


def build_low_remain_block(html, nav_html_list, sort_field, sub_strategy, tables, use_personal_features=False):
    sql = """
    SELECT DISTINCT d.* , e.hold_id, e.hold_amount as 持有数量
  FROM (
      SELECT c.data_id as nid, c.bond_code, c.stock_code, c.cb_name_id as 名称, remain_amount as '余额(亿元)', 
        cb_price2_id as 转债价格, round(cb_premium_id*100,2) || '%' as 溢价率, 
        round(""" + sort_field + """,2) as 双低值,
        round(cb_mov2_id * 100, 2) || '%' as 可转债涨跌, round(cb_mov_id * 100, 2) || '%' as 正股涨跌,
        round(cb_trade_amount2_id * 100,2) || '%' as '换手率(%)', 
        c.stock_name as 正股名称, c.industry as '行业', c.sub_industry as '子行业', e.theme as 题材概念,
        round(bt_yield*100,2) || '%' as 到期收益率, round(cb_price2_id + cb_premium_id * 100, 2) as 双低值,
        
        rank_gross_rate ||'【' || level_gross_rate || '】' as 毛利率排名,rank_net_margin ||'【' || level_net_margin || '】' as 净利润排名,
        rank_net_profit_ratio ||'【' || level_net_profit_ratio || '】'  as 利润率排名, rank_roe ||'【' || level_roe || '】' as ROE排名,
        rank_pe ||'【' || level_pe || '】' as PE排名, rank_pb ||'【' || level_pb || '】' as PB排名,
        rank_net_asset ||'【' || level_net_asset || '】' as 净资产排名, rank_market_cap ||'【' || level_market_cap || '】' as 市值排名,
        stock_total as 综合评分, 
        
        round(s.revenue,2) as '营收(亿元)',s.yoy_revenue_rate || '%' as '营收同比',
        gross_rate||'|' || avg_gross_rate as '毛利率|行业均值',  
        round(s.net,2)||'|' || avg_net_margin as '净利润|均值(亿元)', s.yoy_net_rate || '%' as '净利润同比', 
        s.margin ||'|' || avg_net_profit_ratio as '利润率|行业均值', s.yoy_margin_rate || '%' as '利润率同比', 
        s.roe ||'|' || avg_roe as 'ROE|行业均值', s.yoy_roe_rate || '%' as 'ROE同比', 
        round(s.al_ratio,2) || '%' as 负债率, s.yoy_al_ratio_rate || '%' as '负债率同比', 
        s.pe||'|' || avg_pe as 'PE(动)|均值',  
        c.stock_pb||'|' || avg_pb as 'PB|行业均值', 
        net_asset||'|' || avg_net_asset as '净资产|行业均值', 
        market_cap||'|' || avg_market_cap as '市值|均值(亿元)', 
        round(cb_to_share_shares * 100,2) || '%'  as '余额/股本(%)', cb_trade_amount_id as '成交额(百万)',
                
        fact_trend || '|' || fact_money || '|' || fact_news || '|' || fact_industry || '|' || fact_base as '技术|资金|消息|行业|基本面',  
        trade_suggest as 操作建议,
        
        rating as '信用', duration as 续存期, cb_ma20_deviate as 'ma20乖离', cb_hot as 热门度, 
        e.interest as 各期利息, case when e.ensure is not null then  '有' else  '无' END as 担保, case when e.buy_back_term is not null then  e.buy_back_term else  '无' END as 回售条款, 
        case when e.down_revise_term is not null then  e.down_revise_term else  '无' END as 下修条款, case when e.enforce_get_term is not null then  e.enforce_get_term else  '无' END as 强赎条款 
        
  
        from (changed_bond_view c left join stock_report s on c.stock_code = s.stock_code)
                  left join changed_bond_extend e on c.bond_code = e.bond_code
        --and cb_premium_id * 100 < 30 
        where remain_amount < 3 
        --and cb_price2_id < 110
        ORDER by """ + sort_field + """ ASC
        limit 10
        ) d left join 
        (select id as hold_id, bond_code, cb_name_id, hold_price, hold_amount 
        from hold_bond 
        where strategy_type='低余额+双低策略轮动'
        ) e 
        on d.bond_code = e.bond_code            
            """
    get_label = lambda row: row['名称'].replace('转债', '') + '(' + str(round(row['余额(亿元)'], 1)) + '亿)'
    html = generate_strategy_table_html(sql, "低余额+双低策略", "余额<3亿, " + sub_strategy + "top10", html, tables,
                                        get_label=get_label, nav_html_list=nav_html_list,
                                        use_personal_features=use_personal_features)
    return html


if __name__ == "__main__":
    utils.trade_utils.calc_mid_data()

    # draw_market_view(True)
    print("processing is successful")
