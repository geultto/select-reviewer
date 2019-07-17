import datetime
import json
import os
import sqlite3
import random
import argparse
from slacker import Slacker

parser = argparse.ArgumentParser()
parser.add_argument("--initdb", help="init db", type=bool, default=False)
flag = parser.parse_args()

TEAM_CNT = 6  # 팀 개수
MAX_TEAM_MEMBER_CNT = 10 # 한팀에 최대 멤버
secret_key = os.environ.get('SECRET_KEY', None)
SLACK_TOKEN = secret_key
SLACK_CHANNEL = '0_공지사항'
file_path = os.path.dirname(os.path.abspath(__file__))

def create_db():
    # SQLite DB 연결
    conn = sqlite3.connect(f"{file_path}/random_reviewer.db")

    # Connection 으로부터 Cursor 생성
    cur = conn.cursor()

    cur.execute("CREATE TABLE run_date(id INTEGER primary key, date VARCHAR )")
    cur.execute("CREATE TABLE team(id INTEGER primary key, name char)")
    cur.execute("CREATE TABLE user(id INTEGER primary key, name char, team_id INTEGER , "
                "team_reviewer_num integer , "
                "team_reviewer VARCHAR , "
                "past_other_team_reviewers TEXT ,"
                "other_team_reviewer varchar ,"
                "other_team_review_cnt integer,"
                "constraint user_team_fk foreign key (team_id) references team);")

    # 트랜젝션의 내용을 DB에 반영함
    conn.commit()

    # Connection 닫기
    conn.close()


def insert_basic_data():
    team_list = {}
    pwd = os.getcwd()

    # 1. 각 팀원들 명단을 가져온다
    f = open(pwd + "/memo/team.txt", 'r')
    for i in range(0, TEAM_CNT):
        temp = f.readline().split('-')
        team_name = temp[0]
        team_member = temp[1].replace('\n', '').split(', ')
        team_list[team_name] = team_member

    print(team_list)

    f.close()

    #2. db에 데이터 insert
    conn = sqlite3.connect(f"{file_path}/random_reviewer.db") # SQLite DB 연결
    cur = conn.cursor() # Connection 으로부터 Cursor 생성
    for i, team in enumerate(team_list.keys()):
        q = "insert into team values({},'{}')".format(i+1, team)
        cur.execute(q)

    user_num = 1
    team_num = 1
    for team_name, member in team_list.items():
        review_index = 0
        for user in member:
            q = "insert into user values({},'{}',{},{},'','','',{})".format(user_num, user, team_num, review_index, 0)
            cur.execute(q)
            user_num += 1
            review_index += 1
        team_num += 1

    # 트랜젝션의 내용을 DB에 반영함
    conn.commit()

    # Connection 닫기
    conn.close()


def manufacture_user_db(_cur):
    _team_member_list = {}

    _cur.execute("SELECT * FROM TEAM")
    _team_list = _cur.fetchall() # 각 팀 이름
    _cur.execute("SELECT * FROM USER")
    _user_info_list = _cur.fetchall()  # 모든 user

    _user_list = []

    # DB에서 가져온 데이터들을 각 팀별로 가공(쿼리 한번만 쓰기 위해서..) 그냥 filter 로 팀별 쿼리 날리는게 나을지 고민중
    for team_id, team_name in _team_list:
        _team_member_list[team_name] = {}
        for user in _user_info_list:
            # id, name, team_fk, team_review, other_team_review
            if team_id == user[2]:
                if not _team_member_list.get(team_name).get(user[1]):
                    _team_member_list.get(team_name)[user[1]] = {
                        "id": user[0],
                        "team_reviewer_num": user[3],
                        "team_reviewer": user[4],
                        "past_other_team_reviewers": user[5],
                        "other_team_reviewer": user[6],
                        "other_team_review_cnt": user[7] # 다른 팀들이 review 한 횟수( 전체 인원수 이상이 되면 past_other_team_reivewer 리셋
                    }
                    _user_list.append(user[1])

    return _team_list, _team_member_list, _user_info_list, _user_list


def create_random_viewer():
    # SQLite DB 연결
    conn = sqlite3.connect(f"{file_path}/random_reviewer.db")

    # Connection 으로부터 Cursor 생성
    cur = conn.cursor()

    cur.execute("SELECT date FROM run_date WHERE id=1")
    run_date_list = cur.fetchall()

    if run_date_list:
        run_date_str = run_date_list[0][0]  # 좀 지저분 하긴 하지만, 일단 1개만 쓸거라..
        past_run_date = datetime.datetime.strptime(run_date_str, '%Y-%m-%d') + datetime.timedelta(days=14)
        today = datetime.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

        # 2주가 되지 않으면 함수 실행 X
        if today < past_run_date:
            return

        # 스크립트 실행 날짜 업데이트
        q = "UPDATE run_date SET date='{}' WHERE id=1".format(today.strftime('%Y-%m-%d'))
        cur.execute(q)
    else:
        # 스크립트 첫 실행
        run_date = datetime.datetime.today().strftime('%Y-%m-%d')
        q = "INSERT INTO run_date VALUES ({},'{}')".format(1, run_date)
        cur.execute(q)

    team_list, team_member_list, user_info_list, user_list = manufacture_user_db(cur)

    user_cnt = len(user_list) # 모든 user 카운트
    check_overlap_user_list = [] # 이번주 랜덤 중 중복으로 발생하는 다른팀 리뷰어 체크하기 위한 list
    temp_user_list = user_list.copy()

    for team, member in team_member_list.items():
        for me in member:
            # 1. 멤버 리뷰 설정
            my_member = member.copy()
            my_member.pop(me) # 본인 이름 제외
            my_member_list = list(my_member.keys())

            max_index = len(my_member) # 멤버 최대 index 값
            index = team_member_list[team][me].get('team_reviewer_num')

            # 멤버끼리는 시프트 시켜서 reviewer 설정
            if index >= max_index:
                index = 0

            # 2. 다른 팀 멤버 리뷰 설정
            my_past_otr_string = team_member_list[team][me].get( # 과거에 다른팀 리뷰어 했던 사람들(string)
                'past_other_team_reviewers'
            )
            my_past_otr_list = my_past_otr_string.split(',')

            while True:
                # temp_user_list 에서 본인 포함 + 우리팀 멤버 제외한 리스트에서 랜덤
                random_choice_list = list(set(temp_user_list) - set(list(member.keys())))

                # 남은 사람중 우리팀 인원 뺐을때 빈 리스트
                # 남은 사람 중 내가 과거에 했던 사람들 뺏을때 빈 리스트일 경우
                # -> (이때는 어쩔수 없이 한 주에 다른 사람과 동일한 `다른팀 리뷰어`가 나올 수 있음 +
                #     우리팀 제외 모든사람이 리뷰한 경우 안나오는 '리뷰어가 있을수도 있음[사이클 마지막쯤 : 전체인원-본인팀 인원 cnt])
                #     ? 정의가 맞는지 좀 헷갈리네요
                # but 한 사이클(max_review_cnt) 내에서 내가 리뷰한 리뷰어에 중복은 있을수 없음
                if not random_choice_list or not list(set(random_choice_list) - set(my_past_otr_list)):
                    temp_user_list = user_list.copy()
                    random_choice_list = list(set(temp_user_list) - set(my_member_list))

                other_team_reviewer = random.choice(random_choice_list)

                # 자기 자신이 아니고, 과거 리뷰했던 사람이 아닐 경우 -> 리뷰어 지정
                if other_team_reviewer is not me and other_team_reviewer not in my_past_otr_list:
                    review_cnt = team_member_list[team][me].get('other_team_review_cnt')
                    ot_reviewer_idx = temp_user_list.index(other_team_reviewer)
                    temp_user_list.pop(ot_reviewer_idx) # 한 주내에 최대한 중복되지 않게 하기 위함 + 랜덤 선택할때 선택지 줄이기 위해

                    if review_cnt >= user_cnt - MAX_TEAM_MEMBER_CNT: # 리뷰 카운트(user_cnt - MAX_TEAM_MEMBER_CNT 이상 이면 리셋)
                        add_past_reviewer = other_team_reviewer + ','
                        review_cnt = 1
                    else:
                        add_past_reviewer = my_past_otr_string + other_team_reviewer + ','
                        check_overlap_user_list.append(other_team_reviewer)
                        review_cnt += 1

                    # 우리팀 리뷰어, 다른팀 리뷰어 한번에 쿼리
                    q = "UPDATE user SET team_reviewer_num={}, team_reviewer='{}', " \
                        "past_other_team_reviewers='{}', other_team_reviewer='{}', other_team_review_cnt={}" \
                        " WHERE name='{}'".format(
                            index + 1, my_member_list[index],add_past_reviewer, other_team_reviewer, review_cnt, me
                        )

                    cur.execute(q)
                    break

    # 트랜젝션의 내용을 DB에 반영함
    conn.commit()

    # Connection 닫기
    conn.close()


# 콘솔에 출력 and text 파일에 쓰기
def print_my_reviewer():
    slack = Slacker(SLACK_TOKEN)

    # SQLite DB 연결
    conn = sqlite3.connect(f"{file_path}/random_reviewer.db")

    # Connection 으로부터 Cursor 생성
    cur = conn.cursor()

    team_list, team_member_list, user_info_list, user_list = manufacture_user_db(cur)

    json_team_list = [] # json으로 보낼 team 정보 리스트

    file = open("random-reviewer.txt", 'a')
    date = datetime.datetime.today()
    file.write("\n\n\n********* {} 리뷰어 *********\n".format(date.strftime('%Y.%m.%d')))
    for team, member in team_member_list.items():
        file.write("\n---------- {} 팀 이번 주 reviewer ----------".format(team))

        json_member_list = []
        for me in member:
            file.write("\n이름: {}, 팀 reviewer: {}, 다른팀 reviewer: {} ".format(
                me, member.get(me).get('team_reviewer'), member.get(me).get('other_team_reviewer'))
            )
            # 각 멤버 관련된 json 정보
            json_member_list.append({
                "title": "{}".format(me),
                "value": "- 우리팀 리뷰: {}\n- 다른팀 리뷰: {}".format(member.get(me).get('team_reviewer'), member.get(me).get('other_team_reviewer')),
                "style": "good"
            })

        # 각 팀 관련 json 정보
        json_team_list.append({
            "title": "*** {} 팀 이번 주 reviewer ***".format(team),
            "pretext": "".join(["<@{}> ".format(user) for user in member]),
            "color": "#3AA3E3",
            "attachment_type": "default",
            "fields": json_member_list
        })

    slack.chat.post_message(
        SLACK_CHANNEL,
        "{} - 글또 Reviewer Select".format(date.strftime('%y.%m.%d')),
        attachments=json.dumps(json_team_list)
    )
    file.close()

    conn.close()


if __name__ == "__main__":
    if flag.initdb:
        # ------------ 처음에 DB 생성할때만 ------------ #
        create_db()
        insert_basic_data()
    else:
        # ------------ DB 생성 후 ------------ #
        # for i in range(0 ,36): # 36<- 한사이클 돌고 리셋되는 카운트
        create_random_viewer()
        print_my_reviewer()
