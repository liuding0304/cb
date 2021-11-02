# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime

from flask import Blueprint
from flask import render_template, request, url_for, redirect, flash, send_from_directory, session
from flask_login import LoginManager
from flask_login import login_user, login_required, logout_user
from prettytable import from_db_cursor
from sqlalchemy import or_

import utils.table_html_utils
import utils.trade_utils
from config import db_file_path
from crawler import cb_ninwen, cb_jsl, cb_ninwen_detail, stock_10jqka, stock_xueqiu, stock_eastmoney, cb_eastmoney
from jobs import do_update_data_after_trade_is_end, do_update_data_before_trade_is_start
from models import User, ChangedBond, HoldBond, ChangedBondSelect, db, TradeHistory, HoldBondHistory, Task
from utils import trade_utils
from utils.db_utils import get_connect, get_cursor
from utils.html_utils import get_strategy_options_html
from views import view_market, view_my_account, view_my_select, view_my_strategy, view_my_yield, view_up_down, \
    view_my_up_down, view_turnover, view_discount, view_stock, view_tree_map_industry, view_tree_map_price, \
    view_tree_map_premium, view_my_price_list, view_my_trade_history, view_cb_trend, view_up_down_range, view_all_cb, \
    view_enforce_list, view_strategy_group
from views.nav_utils import build_select_nav_html, build_personal_nav_html_list, build_personal_nav_html

cb = Blueprint('cb', __name__)

login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id):  # 创建用户加载回调函数，接受用户 ID 作为参数
    user = User.query.get(int(user_id))  # 用 ID 作为 User 模型的主键查询对应的用户
    return user  # 返回用户对象


@cb.route('/')
def index():
    return render_template("index.html")

@cb.route('/login.html', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    if not username or not password:
        flash('Invalid input.')
        return redirect(url_for('login'))
    else:
        user = User.query.filter_by(name=username).first()
        if user.validate_password(password):
            login_user(user)
            flash('Login success.')

    return render_template('index.html')

@cb.route('/sign.html')
def sign():
    return render_template('index.html', sign=True)


@cb.route('/logout.html')
def logout():
    logout_user()

    return render_template('index.html')

#fixme 废弃掉, 用sync_trade_data代替
@cb.route('/edit_hold_bond.html')
@cb.route('/edit_hold_bond_by_id.html/<id>/')
@cb.route('/edit_hold_bond.html/<bond_code>/')
@login_required
def edit_hold_bond(id='', bond_code=''):
    bond = None
    if id != '':
        bond = db.session.query(HoldBond).filter(HoldBond.id == id).first()
    elif bond_code != '':
        # 先查持有的
        bond = db.session.query(HoldBond).filter(HoldBond.bond_code == bond_code, HoldBond.hold_amount > -1).first()

        # 没有持有过, 转添加操作
        if bond is None:
            bond = db.session.query(ChangedBond).filter(ChangedBond.bond_code == bond_code).first()
            # 先关闭session, 再修改model, 否则会触发update
            db.session.close()
            bond.id = ''

    return render_template("edit_hold_bond.html", bond=bond)


@cb.route('/find_bond_by.html', methods=['GET'])
@login_required
def find_bond_by_code():
    bond_code = request.args.get("bond_code")
    account = request.args.get("account")
    # fixme 打新和其他策略可能同时存在
    # 先找hold_amount>-1的,没有再找hold_amount=-1的
    bond = None
    if bond_code != '':
        if account != '':
            bond = db.session.query(HoldBond).filter(HoldBond.bond_code == bond_code, HoldBond.account == account).first()
        else:
            bond = db.session.query(HoldBond).filter(HoldBond.bond_code == bond_code).first()

    if bond is None:
        if bond_code != '':
            bond = ChangedBond.query.filter_by(bond_code=bond_code).first()

        if bond is not None:
            # 先关闭session, 再修改model, 否则会触发update
            db.session.close()
            bond.id = ''
            return dict(bond)
        raise Exception('not find bond by code: ' + bond_code)
    else:
        return dict(bond)


@cb.route('/find_bond_by_name.html/<bond_name>/', methods=['GET'])
@login_required
def find_bond_by_name(bond_name):

    if bond_name != '':
        bonds1 = db.session.query(HoldBond).filter(or_(HoldBond.cb_name_id.like('%' + bond_name + '%'), HoldBond.pinyin.like('%' + bond_name + '%'))).all()

        bonds2 = db.session.query(ChangedBond).filter(or_(ChangedBond.cb_name_id.like('%' + bond_name + '%'), ChangedBond.pinyin.like('%' + bond_name + '%'))).all()

        bonds = []
        bonds.extend(bonds1)
        bonds.extend(bonds2)

        # changedbond的id非holdbond的id, 故排除
        return json.dumps(bonds, default=lambda o: o.to_dict('id') if type(o) == ChangedBond else (
            o.to_dict() if type(o) != datetime else str(o)))

    return "{}"


@cb.route('/view_my_select.html')
@login_required
def my_select_view():
    user_id = session.get('_user_id')
    title, navbar, content = view_my_select.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/delete_selected_bond.html/<ids>/')
@login_required
def delete_selected_bond(ids):
    if ids is None or ids.strip(' ') == '':
        print("parameter ids is invalid.")

    ss = ids.split(',')
    db.session.query(ChangedBondSelect)\
        .filter(ChangedBondSelect.id.in_(ss))\
        .update({ChangedBondSelect.is_deleted: 1})
    db.session.commit()

    return 'OK'


@cb.route('/edit_changed_bond_select.html')
@cb.route('/edit_changed_bond_select.html/<bond_code>/')
@login_required
def edit_changed_bond_select(bond_code=''):
    bond = None
    if bond_code != '':
        bond = db.session.query(ChangedBondSelect).filter(ChangedBondSelect.bond_code == bond_code).first()

    type = None
    if bond is not None:
        type = bond.strategy_type
    options = get_strategy_options_html(type)

    navbar = build_select_nav_html('/edit_changed_bond_select.html')

    return render_template("edit_changed_bond_select.html", bond=bond, strategy_options=options, navbar=navbar)


@cb.route('/find_changed_bond_select_by_code.html', methods=['GET'])
@login_required
def find_changed_bond_select_by_code():
    bond_code = request.args.get("bond_code")
    bond_name = request.args.get("bond_name")
    bond = None
    if bond_code != '':
        bond = db.session.query(ChangedBondSelect).filter(ChangedBondSelect.bond_code == bond_code).first()
        if bond is None:
            bond = db.session.query(ChangedBond).filter(ChangedBond.bond_code == bond_code).first()
            if bond is not None:
                # 先关闭session, 再修改model, 否则会触发update
                db.session.close()
                bond.id = ''
    elif bond_name != '':
        bond = db.session.query(ChangedBondSelect).filter(ChangedBondSelect.cb_name_id.like('%' + bond_name + '%')).first()
        if bond is None:
            bond = db.session.query(ChangedBond).filter(ChangedBond.cb_name_id.like('%' + bond_name + '%')).first()
            if bond is not None:
                # 先关闭session, 在修改model, 否则会触发update
                db.session.close()
                bond.id = ''

    if bond is None:
        raise Exception('not find bond by code/name: ' + bond_code + "," + bond_name)
    else:
        return dict(bond)

@cb.route('/find_changed_bond_select_by_name.html/<bond_name>/', methods=['GET'])
@login_required
def find_changed_bond_select_by_name(bond_name):
    bonds = None
    if bond_name != '':
        bonds = db.session.query(ChangedBondSelect).filter(or_(ChangedBondSelect.cb_name_id.like('%' + bond_name + '%'), ChangedBondSelect.pinyin.like('%' + bond_name + '%')), ChangedBondSelect.is_deleted != 1).all()
        if len(bonds) == 0:
            bonds = db.session.query(ChangedBond).filter(or_(ChangedBond.cb_name_id.like('%' + bond_name + '%'), ChangedBond.pinyin.like('%' + bond_name + '%'))).all()
            if len(bonds) > 0:  # changed bond的id非select的id, 故排除
                return json.dumps(bonds, default=lambda o: o.to_dict('id') if type(o) != datetime else str(o))

    return json.dumps(bonds, default=lambda o: o.to_dict() if type(o) != datetime else str(o))

@cb.route('/save_changed_bond_select.html', methods=['POST'])
@login_required
def save_changed_bond_select():
    id = request.form['id']
    changed_bond_select = None
    if id is None or id.strip(' ') == '':
        changed_bond_select = ChangedBondSelect()
    else:
        changed_bond_select = db.session.query(ChangedBondSelect).filter(ChangedBondSelect.id == id).first()

    bond_code = request.form['bond_code']
    if bond_code is None or bond_code.strip(' ') == '':
        raise Exception('转债代码不能为空')

    changed_bond_select.bond_code = bond_code

    cb_name_id = request.form['cb_name_id']
    if cb_name_id is None or cb_name_id.strip(' ') == '':
        raise Exception('转债名称不能为空')

    changed_bond_select.cb_name_id = cb_name_id
    changed_bond_select.pinyin = request.form['pinyin']

    strategy_type = request.form['strategy_type']
    if strategy_type is not None and strategy_type.strip(' ') != '':
        changed_bond_select.strategy_type = strategy_type

    memo = request.form['memo']
    # if memo is not None and memo.strip(' ') != '':
    changed_bond_select.memo = memo

    changed_bond_select.modify_date = datetime.now()
    if id is None or id.strip(' ') == '':
        changed_bond_select.create_date = datetime.now()
        db.session.add(changed_bond_select)
    db.session.commit()

    options = get_strategy_options_html(None)

    navbar = build_select_nav_html('/edit_changed_bond_select.html')

    return render_template("edit_changed_bond_select.html", result='save is successful', strategy_options=options, navbar=navbar)


#fixme 废弃掉, 用sync_trade_data代替
@cb.route('/save_hold_bond.html', methods=['POST'])
@login_required
def save_hold_bond():
    id = request.form['id']
    hold_bond = None
    is_new = id is None or id.strip(' ') == ''
    if is_new:
        #新增操作
        hold_bond = HoldBond()
    else:
        # 更新操作
        hold_bond = db.session.query(HoldBond).filter(HoldBond.id == id).first()

    bond_code = request.form['bond_code']
    if bond_code is None or bond_code.strip(' ') == '':
        raise Exception('转债代码不能为空')

    hold_bond.bond_code = bond_code

    if bond_code.startswith('11'):
        hold_bond.hold_unit = 10
    else:
        hold_bond.hold_unit = 1

    cb_name_id = request.form['bond_name']
    if cb_name_id is None or cb_name_id.strip(' ') == '':
        raise Exception('转债名称不能为空')

    hold_bond.cb_name_id = cb_name_id
    hold_bond.cb_name_id = request.form['pinyin']

    hold_amount = request.form['hold_amount']
    if hold_amount is None or hold_amount.strip(' ') == '':
        raise Exception('持有数量不能为空')

    hold_bond.hold_amount = int(hold_amount)

    hold_price = request.form['hold_price']
    if hold_price is None or hold_price.strip(' ') == '':
        raise Exception('持有价格不能为空')

    hold_bond.hold_price = float(hold_price)
    # 重置一下累积金额信息, 避免下次持仓价格计算错误
    if is_new:
        # 持仓金额同时增加
        hold_bond.sum_buy += hold_bond.hold_price * hold_bond.hold_amount
    else:
        # 增加数量
        delta = float(hold_price) - hold_bond.hold_price
        # 持仓金额同时增加
        hold_bond.sum_buy += delta * hold_bond.hold_amount

    account = request.form['account']
    if account is not None and account.strip(' ') != '':
        hold_bond.account = account

    strategy_type = request.form['strategy_type']
    if strategy_type is None or strategy_type.strip(' ') == '':
        raise Exception('必须指定策略类型')

    hold_bond.strategy_type = strategy_type

    memo = request.form['memo']
    if memo is not None and memo.strip(' ') != '':
        hold_bond.memo = memo

    ymd = trade_utils.get_ymd()
    if is_new:
        # 增加开始时间
        hold_bond.start_date = datetime.now()
        db.session.add(hold_bond)
    else:
        hold_bond.modify_date = datetime.now()

    db.session.commit()

    return redirect(request.form['back_url'])


@cb.route('/save_trade_data.html', methods=['POST'])
@login_required
def save_trade_data():
    id = request.form['id']
    hold_bond = None
    is_new = id is None or id.strip(' ') == ''
    if is_new:
        # 新增操作
        hold_bond = HoldBond()
    else:
        # 更新操作
        hold_bond = db.session.query(HoldBond).filter(HoldBond.id == id).first()

    bond_code = request.form['bond_code']
    if bond_code is None or bond_code.strip(' ') == '':
        raise Exception('转债代码不能为空')

    hold_bond.bond_code = bond_code

    is_sh_market = bond_code.startswith('11')

    if is_sh_market:
        hold_bond.hold_unit = 10
    else:
        hold_bond.hold_unit = 1

    cb_name_id = request.form['bond_name']
    if cb_name_id is None or cb_name_id.strip(' ') == '':
        raise Exception('转债名称不能为空')

    hold_bond.cb_name_id = cb_name_id

    trade_amount = request.form['trade_amount']
    if trade_amount is None or trade_amount.strip(' ') == '':
        raise Exception('成交量不能为空')

    if int(trade_amount) < 0:
        raise Exception("成交量必须大于0")

    trade_price = request.form['trade_price']
    if trade_price is None or trade_price.strip(' ') == '':
        raise Exception('成交价不能为空')

    direction = request.form['direction']
    if direction is None or direction.strip(' ') == '':
        raise Exception('必须指定买卖方向')

    is_sell = direction == 'sell'
    if is_sell:
        if int(trade_amount) > hold_bond.hold_amount:
            raise Exception("成交量(" + trade_amount + ")不能超过持有量(" + str(hold_bond.hold_amount) + ")")

    account = request.form['account']
    if account is None or account.strip(' ') == '':
        raise Exception("必须指定交易账户")

    hold_bond.account = account

    # 计算持仓成本
    fee = trade_utils.calc_hold_price(hold_bond, direction, trade_amount, trade_price)

    strategy_type = request.form['strategy_type']
    if strategy_type is None or strategy_type.strip(' ') == '':
        raise Exception('必须指定策略类型')

    hold_bond.strategy_type = strategy_type

    ymd = trade_utils.get_ymd()
    if is_new:
        # 增加开始时间
        hold_bond.start_date = datetime.now()
        db.session.add(hold_bond)
        # 获取id, 强刷
        db.session.flush()
    else:
        hold_bond.modify_date = datetime.now()

    # 保存成交记录
    trade_history = TradeHistory()
    trade_history.bond_code = bond_code
    trade_history.fee = fee
    user_id = session.get('_user_id')
    trade_history.owner_id = user_id
    trade_history.cb_name_id = cb_name_id
    trade_history.account = account
    trade_history.strategy_type = strategy_type
    trade_history.price = trade_price
    trade_history.amount = -int(trade_amount) if is_sell else trade_amount
    trade_history.hold_id = hold_bond.id
    db.session.add(trade_history)

    db.session.commit()

    options = get_strategy_options_html(None)


    return render_template("sync_trade_data.html", bond=None, navbar=build_personal_nav_html(), result='operation is successful', strategy_options=options)


@cb.route('/un_save_trade_data.html/<id>', methods=['GET'])
@login_required
def un_save_trade_data(id):
    trade_history = db.session.query(TradeHistory).filter(TradeHistory.id == id).first()
    if trade_history is None:
        raise Exception("not get trade_history by id:"+str(id))

    hold_id = trade_history.hold_id
    hold_bond = db.session.query(HoldBond).filter(HoldBond.id == hold_id).first()
    is_new_hold_bond = False
    if hold_bond is None:
        # 可能被归档了, 需要先从归档中恢复
        hold_bond_history = db.session.query(HoldBondHistory).filter(HoldBondHistory.id == hold_id).first()
        if hold_bond_history is None:
            raise Exception('not get hold_bond by id:' + str(hold_id))
        else:
            hold_bond = HoldBond()
            hold_bond.copy(hold_bond_history)
            is_new_hold_bond = True

    # 重新计算持仓成本
    trade_utils.re_calc_hold_price(hold_bond, trade_history)

    try:
        if is_new_hold_bond:
            db.session.add(hold_bond)
            db.session.query(HoldBondHistory).filter(HoldBondHistory.id == hold_id).delete()
        trade_history.is_delete = 1
        db.session.commit()
    except Exception as err:
        print('un_save_trade_data is failure. err:' + str(err))
        db.session.rollback()

    return 'OK'


@cb.route('/sync_jsl_bond_data.html')
@login_required
def sync_jsl_bond_data():
    return render_template("sync_jsl_bond_data.html")


@cb.route('/sync_trade_data.html/<id>/')
@cb.route('/new_sync_trade_data.html/<bond_code>/')
@cb.route('/new_sync_trade_data.html')
@login_required
def sync_trade_data(id='', bond_code=''):
    bond = None
    if id != '':
        bond = db.session.query(HoldBond).filter(HoldBond.id == id).first()
    elif bond_code != '':
        bond = db.session.query(ChangedBond).filter(ChangedBond.bond_code == bond_code).first()
        # 先关闭session, 在修改model, 否则会触发update
        db.session.close()
        bond.id = ''

    options = get_strategy_options_html(None
                                        if bond is None
                                        else (bond.strategy_type if hasattr(bond, 'strategy_type') else None))

    return render_template("sync_trade_data.html", bond=bond, navbar=build_personal_nav_html(), strategy_options=options)


@cb.route('/view_up_down.html')
def up_down_view():
    user_id = session.get('_user_id')
    title, navbar, content = view_up_down.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_up_down_range.html')
def up_down_range_view():
    user_id = session.get('_user_id')
    title, navbar, content = view_up_down_range.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_tree_map_industry.html')
def industry_tree_map_view():
    key = request.args.get("key")
    rise = request.args.get("rise")
    user_id = session.get('_user_id')
    title, navbar, content = view_tree_map_industry.draw_view(user_id is not None, key, rise)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_tree_map_price.html')
def price_tree_map_view():
    key = request.args.get("key")
    end, start = parse_range_value(key, '元')

    rise = request.args.get("rise")
    user_id = session.get('_user_id')
    title, navbar, content = view_tree_map_price.draw_view(user_id is not None, key, start, end, rise)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_tree_map_premium.html')
def premium_tree_map_view():
    key = request.args.get("key")
    end, start = parse_range_value(key, '%')
    rise = request.args.get("rise")
    user_id = session.get('_user_id')
    title, navbar, content = view_tree_map_premium.draw_view(user_id is not None, key, start, end, rise)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


def parse_range_value(key, suffix):
    start = None
    end = None
    if key is not None and key.strip(' ') != '':
        key = key.replace(suffix, '')
        if key.find('~') >= 1:
            ss = key.split('~')
            start = int(ss[0])
            end = int(ss[1])
        elif key.find('<=') >= 0:
            start = -sys.maxsize
            end = int(key.replace('<=', ''))
        else:
            start = int(key.replace('>', ''))
            end = sys.maxsize
    return end, start


@cb.route('/view_discount.html')
def discount_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_discount.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_all_cb.html')
def all_cb_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_all_cb.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_stock.html')
def stock_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_stock.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_turnover.html')
def turnover_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_turnover.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_my_up_down.html')
@login_required
def my_up_down_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_my_up_down.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_my_price_list.html')
@login_required
def my_price_list_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_my_price_list.draw_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)

@cb.route('/view_my_strategy.html')
@login_required
def my_strategy_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_my_strategy.draw_my_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_my_yield.html')
@login_required
def my_yield_view():
    title, navbar, content = view_my_yield.draw_my_view()
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_my_trade_history.html/<bond_code>/')
@cb.route('/view_my_trade_history.html')
@login_required
def my_trade_history_view(bond_code=''):
    user_id = session.get('_user_id')
    title, navbar, content = view_my_trade_history.draw_my_view(user_id, bond_code)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_my_account.html')
@login_required
def my_account_view():
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_my_account.draw_my_view(user_id is not None)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)

@cb.route('/view_market.html')
def market_view():
    # current_user = None
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_market.draw_market_view(user_id)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_strategy_group.html')
def strategy_group_view():
    # current_user = None
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_strategy_group.draw_view(user_id)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)


@cb.route('/view_enforce_list.html')
def enforce_list_view():
    # current_user = None
    user_id = session.get('_user_id')
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_enforce_list.draw_view(user_id)
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)

@cb.route('/view_trend.html')
def trend_view():
    # current_user = None
    utils.trade_utils.calc_mid_data()
    title, navbar, content = view_cb_trend.draw_view()
    return render_template("page_with_navbar.html", title=title, navbar=navbar, content=content)

@cb.route('/eastmoney_update_data.html')
@cb.route('/realtime_update_data.html')
# @login_required
def realtime_update_data():
    return cb_eastmoney.fetch_data()

@cb.route('/easy_update_data.html')
@login_required
def jsl_update_data():
    return cb_jsl.fetch_data()

@cb.route('/cb_ninwen.html')
@login_required
def ninwen_update_data():
    return cb_ninwen.fetch_data()

@cb.route('/cb_ninwen_detail.html/<task_name>/', methods=['GET'])
@login_required
def ninwen_detail_update_data(task_name):
    cb_ninwen_detail.fetch_data(task_name)
    return 'OK'

@cb.route('/stock_10jqka.html/<task_name>/', methods=['GET'])
@login_required
def stock_10jqka_update_data(task_name):
    stock_10jqka.fetch_data(task_name)
    return 'OK'

@cb.route('/stock_eastmoney.html/<task_name>/', methods=['GET'])
@login_required
def stock_eastmoney_update_data(task_name):
    stock_eastmoney.fetch_data(task_name)
    return 'OK'

@cb.route('/stock_xueqiu.html/<task_name>/', methods=['GET'])
@login_required
def stock_xueqiu_update_data(task_name):
    stock_xueqiu.fetch_data(task_name)
    return 'OK'

@cb.route('/get_task_data.html/<task_name>/', methods=['GET'])
@login_required
def get_task_data(task_name):
    task = db.session.query(Task).filter(Task.name == task_name).first()
    if task is None:
        task = Task()
    return dict(task)

@cb.route('/download_db_data.html')
@login_required
def download_db_data():
    today = datetime.now()
    ymd = today.strftime('%Y-%m-%d')
    file_name = 'dump/data_' + ymd + '.sql'

    with open(file_name, 'w') as f:
        with get_connect() as con:
            for line in con.iterdump():
                f.write('%s\n' % line)

    # 需要知道2个参数, 第1个参数是本地目录的path, 第2个参数是文件名(带扩展名)
    directory = os.getcwd()  # 假设在当前目录
    return send_from_directory(directory, file_name, as_attachment=True)

@cb.route('/upload_db_data.html')
@login_required
def upload_db_data():
    return render_template("upload_db_data.html")

@cb.route('/save_db_data.html', methods=['POST'])
@login_required
def save_db_data():
    # 删除整个db
    os.unlink(db_file_path)
    # 获取文件(字符串?)
    file = request.files['file']
    s = file.read().decode('utf-8')
    # 灌入上传的数据
    with get_connect() as con:
        con.executescript(s)

    return 'OK'


@cb.route('/query_database.html', methods=['POST', 'GET'])
@login_required
def query_database_view():
    table_html = ''
    sql_code = ''
    table_height_style = ''
    if len(request.form) > 0:
        sql_code = request.form['sql_code']
        if sql_code is None or sql_code.strip(' ') == '':
            raise Exception('SQL不能为空')

        if not sql_code.lower().strip().startswith('select'):
            raise Exception("仅允许select操作")

        cur = get_cursor(sql_code)
        table = from_db_cursor(cur)

        if table.rowcount > 10:
            table_height_style = """style="height:500px" """

        table_html = utils.table_html_utils.build_table_html()

    return render_template("query_database.html", table_html=table_html, sql_code=sql_code, table_height_style=table_height_style)


@cb.route('/update_database.html')
@login_required
def update_database():
    return render_template("update_database.html")


@cb.route('/execute_sql.html', methods=['POST'])
@login_required
def execute_sql():
    sql_code = request.form['sql_code']
    if sql_code is None or sql_code.strip(' ') == '':
        raise Exception('SQL不能为空')

    if not sql_code.lower().strip().startswith('update') and not sql_code.lower().strip().startswith('insert'):
        raise Exception("仅允许update/insert操作")

    with get_connect() as con:
        con.executescript(sql_code)

    return 'OK'


@cb.route('/update_data_after_trade_is_end.html')
@login_required
def update_data_after_trade_is_end():
    return do_update_data_after_trade_is_end()


@cb.route('/update_data_before_trade_is_start.html')
@login_required
def update_data_before_trade_is_start():
    return do_update_data_before_trade_is_start()

