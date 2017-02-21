#!/usr/bin/python
# -*- coding: utf-8 -*-
import codecs
import json
import os
import re
import sys
import threading
import time
import urllib
import urllib2

from datetime import timedelta

UTF8Writer = codecs.getwriter('utf8')
sys.stdout = UTF8Writer(sys.stdout)
os.environ['TZ'] = 'Europe/Moscow'
time.tzset()

telegram_api = 'https://api.telegram.org/TOKEN'

resources = open('files/resources.json', 'r+')
users = json.load(resources)

urlregex = re.compile(
    r'^(?:http)s?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
    r'localhost|'  # localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # ...or ipv4
    r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'  # ...or ipv6
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)


def send_message(chat_id, text, disable_web_page_preview=False, reply_markup=None):
    req = {'chat_id': chat_id, 'text': text,
           'disable_web_page_preview': disable_web_page_preview}
    if reply_markup is not None:
        req = {'chat_id': chat_id, 'text': text,
               'reply_markup': json.dumps(reply_markup)}
    req = urllib.urlencode(req)
    urllib2.urlopen(urllib2.Request(telegram_api + '/sendMessage', req))


def write_resources():
    try:
        resources.seek(0)
        resources.truncate()
        json.dump(users, resources, indent=4, sort_keys=True)
        resources.flush()
    except Exception:
        print('file exception')


def make_message(site):
    if site['state']:
        state = 'UP'
    else:
        state = 'DOWN'
    if site['retries']:
        return ('%s\n%s is %s\nDuration: %s\nRetries: %d' % (time.ctime(), site['url'], state,
                                                             timedelta(seconds=time.time() - site['last_change_time']),
                                                             site['retries']))
    else:
        return ('%s\n%s is %s\nDuration: %s' % (time.ctime(), site['url'], state,
                                                timedelta(seconds=time.time() - site['last_change_time'])))


def change_state_down(site):
    if site['state']:
        site['state'] = False
        message = make_message(site)
        site['last_change_time'] = time.time()
        print(message)
        send_message(site['user_id'], message, True)
        write_resources()


def change_state_up(site):
    if not site['state']:
        site['state'] = True
        message = make_message(site)
        site['last_change_time'] = time.time()
        print(message)
        send_message(site['user_id'], message, True)
        write_resources()


def checker(site):
    if 'last_change_time' not in site.keys():
        site['state'] = True
        site['last_change_time'] = time.time()
        site['retries'] = 0
    while not threads[site['user_id']][site['url']]['kill_thread']:
        try:
            response = urllib2.urlopen(site['url'], timeout=10)
        except Exception:
            site['retries'] += 1
            if site['retries'] >= 3:
                change_state_down(site)
        else:
            if response.getcode() != 200:
                site['retries'] += 1
                if site['retries'] >= 3:
                    change_state_down(site)
            if response.getcode() == 200 and not site['state']:
                site['retries'] = 0
                change_state_up(site)
        time.sleep(1)


def command_handler():
    offset = 0
    users_command = {}
    while True:
        try:
            response = urllib2.urlopen(urllib2.Request(telegram_api + '/getUpdates'),
                                       urllib.urlencode({'offset': offset, 'timeout': 100}), timeout=120)
        except Exception:
            pass
        else:
            response = json.loads(response.read())
            if response['ok']:
                for update in response['result']:
                    offset = update['update_id'] + 1
                    update['message']['chat']['id'] = str(update['message']['chat']['id'])
                    if update['message']['chat']['id'] in users.keys():
                        if update['message']['text'] == "/status":
                            message = ''
                            for site in users[update['message']['chat']['id']]:
                                message += make_message(site) + "\n\n"
                            send_message(update['message']['chat']['id'], message, True)
                        elif (update['message']['text'] == "/cancel" and
                                      update['message']['chat']['id'] in users_command):
                            send_message(update['message']['chat']['id'], 'Canceled',
                                         reply_markup={'hide_keyboard': True})
                            users_command.pop(update['message']['chat']['id'])
                        elif update['message']['text'] in ["/addurl", "/delurl"]:
                            users_command[update['message']['chat']['id']] = update['message']['text']
                            if update['message']['text'] == "/delurl":
                                keyboard = {'keyboard': [], 'one_time_keyboard': True,
                                            'resize_keyboard': True}
                                for site in users[update['message']['chat']['id']]:
                                    keyboard['keyboard'].append([site['url']])
                                send_message(update['message']['chat']['id'], 'Now send me URL',
                                             reply_markup=keyboard)
                            if update['message']['text'] == "/addurl":
                                send_message(update['message']['chat']['id'], 'Now send me URL')
                        elif update['message']['chat']['id'] in users_command:
                            if (users_command[update['message']['chat']['id']] == "/addurl" and
                                    urlregex.match(update['message']['text'])):
                                users[update['message']['chat']['id']].append({"url": update['message']['text']})
                                site = users[update['message']['chat']['id']][-1]
                                site['user_id'] = update['message']['chat']['id']
                                user_id = update['message']['chat']['id']
                                threads[user_id][site['url']] = {'thread': threading.Thread(
                                    target=checker, args=(site,)), 'kill_thread': False}
                                threads[user_id][site['url']]['thread'].start()
                                send_message(update['message']['chat']['id'], 'Ok')
                                write_resources()
                            elif users_command[update['message']['chat']['id']] == "/delurl":
                                send_message(update['message']['chat']['id'], 'Ok',
                                             reply_markup={'hide_keyboard': True})
                                for idx, site in enumerate(users[update['message']['chat']['id']]):
                                    if site['url'] == update['message']['text']:
                                        user_id = update['message']['chat']['id']
                                        threads[user_id][site['url']]['kill_thread'] = True
                                        threads[user_id][site['url']]['thread'].join()
                                        del threads[user_id][site['url']]
                                        del users[update['message']['chat']['id']][idx]
                                write_resources()
                            users_command.pop(update['message']['chat']['id'])
                        else:
                            print(
                                "Unknown command from user: %s\nCommand: %s" % (update['message']['chat']['first_name'],
                                                                                update['message']['text']))
                    else:
                        print("Unknown user %s %s\n%s" % (update['message']['chat']['id'],
                                                          update['message']['chat']['first_name'],
                                                          update['message'].get('text', '')))


threading.Thread(target=command_handler).start()
threads = {}
for user_id in users:
    for site in users[user_id]:
        if user_id not in threads.keys():
            threads[user_id] = {}
        threads[user_id][site['url']] = {'thread': threading.Thread(target=checker, args=(site,)), 'kill_thread': False}
        threads[user_id][site['url']]['thread'].start()
        site['user_id'] = user_id
