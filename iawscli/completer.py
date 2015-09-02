# -*- coding: utf-8
from __future__ import unicode_literals
from enum import Enum
import sys
import re
import os
import fuzzyfinder
import subprocess
from six.moves import cStringIO
from prompt_toolkit.completion import Completer, Completion
from .utils import shlex_split, shlex_first_token
from .commands import SHORTCUTS_MAP


class AwsCompleter(Completer):
    """
    Completer for AWS commands and parameters.
    """

    def __init__(self, aws_completer,
                 fuzzy_match=False, refresh_instance_ids=True,
                 refresh_instance_tags=True, refresh_bucket_names=True):
        """
        Initialize the completer
        :return:
        """
        self.aws_completer = aws_completer
        self.aws_completions = set()
        self.fuzzy_match = fuzzy_match
        self.instance_ids = []
        self.instance_tags = set()
        self.bucket_names = []
        self.refresh_instance_ids = refresh_instance_ids
        self.refresh_instance_tags = refresh_instance_tags
        self.refresh_bucket_names = refresh_bucket_names
        self.BASE_COMMAND = 'aws'
        self.instance_ids_marker = '[instance ids]'
        self.instance_tags_marker = '[instance tags]'
        self.bucket_names_marker = '[bucket names]'
        self.refresh_resources()

    def refresh_resources_from_file(self, f, p):
        class ResType(Enum):

            INSTANCE_IDS, INSTANCE_TAGS, BUCKET_NAMES = range(3)

        res_type = ResType.INSTANCE_IDS
        with open(f) as fp:
            self.instance_ids = []
            self.instance_tags = set()
            self.bucket_names = []
            instance_tags_list = []
            for line in fp:
                line = re.sub('\n', '', line)
                if line.strip() == '':
                    continue
                elif self.instance_ids_marker in line:
                    res_type = ResType.INSTANCE_IDS
                    continue
                elif self.instance_tags_marker in line:
                    res_type = ResType.INSTANCE_TAGS
                    continue
                elif self.bucket_names_marker in line:
                    res_type = ResType.BUCKET_NAMES
                    continue
                if res_type == ResType.INSTANCE_IDS:
                    self.instance_ids.append(line)
                elif res_type == ResType.INSTANCE_TAGS:
                    instance_tags_list.append(line)
                elif res_type == ResType.BUCKET_NAMES:
                    self.bucket_names.append(line)
            self.instance_tags = set(instance_tags_list)

    def save_resources_to_file(self, f, p):
        with open(f, 'w') as fp:
            fp.write(self.instance_ids_marker + '\n')
            for instance_id in self.instance_ids:
                fp.write(instance_id + '\n')
            fp.write(self.instance_tags_marker + '\n')
            for instance_tag in self.instance_tags:
                fp.write(instance_tag + '\n')
            fp.write(self.bucket_names_marker + '\n')
            for bucket_name in self.bucket_names:
                fp.write(bucket_name + '\n')

    def refresh_resources(self, force_refresh=False):
        """
        Refreshes the AWS resources
        :return: None
        """
        p = os.path.dirname(os.path.realpath(__file__))
        f = os.path.join(p, 'data/RESOURCES.txt')
        if not force_refresh:
            try:
                self.refresh_resources_from_file(f, p)
                print('Loaded resources from cache')
            except IOError:
                print('No resource cache found')
                force_refresh = True
        if force_refresh:
            print('Refreshing resources...')
            if self.refresh_instance_ids:
                print('  Refreshing instance ids...')
                self.generate_instance_ids()
            if self.refresh_instance_tags:
                print('  Refreshing instance tags...')
                self.generate_instance_tags()
            if self.refresh_bucket_names:
                print('  Refreshing bucket names...')
                self.generate_bucket_names()
            print('Done refreshing')
        try:
            self.save_resources_to_file(f, p)
        except IOError as e:
            print(e)

    def generate_instance_ids(self):
        command = "aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId]' --output text"
        try:
            result = subprocess.check_output([command], shell=True)
            result = re.sub('\n', ' ', result)
            self.instance_ids = result.split()
        except Exception as e:
            print(e)

    def generate_instance_tags(self):
        command = "aws ec2 describe-instances --filters 'Name=tag-key,Values=*' --query Reservations[].Instances[].Tags[].Key --output text"
        try:
            result = subprocess.check_output([command], shell=True)
            self.instance_tags = set(result.split('\t'))
        except Exception as e:
            print(e)

    def generate_bucket_names(self):
        command = "aws s3 ls"
        try:
            output = subprocess.check_output([command], shell=True)
            result_list = output.split('\n')
            for result in result_list:
                try:
                    result = result.split()[-1]
                    self.bucket_names.append(result)
                except:
                    pass
        except Exception as e:
            print(e)

    def handle_shortcuts(self, text):
        for key in SHORTCUTS_MAP.keys():
            if key in text:
                # Replace shortcut with full command
                text = re.sub(key, SHORTCUTS_MAP[key], text)
                text = self.handle_subs(text)
        return text

    def handle_subs(self, text):
        if '%s' in text:
            tokens = text.split()
            text = ' '.join(tokens[:-1])
            text = re.sub('%s', tokens[-1], text)
        return text

    def get_res_completions(self, words, word_before_cursor,
                            option_text, resource):
        if words[-1] == option_text or \
            (len(words) > 1 and
                (words[-2] == option_text and word_before_cursor != '')):
            return AwsCompleter.find_matches(
                word_before_cursor,
                resource,
                self.fuzzy_match)

    def get_completions(self, document, _):
        """
        Get completions for the current scope.
        :param document:
        :param _: complete_event
        """
        # Capture the AWS CLI autocompleter and store it in a string
        old_stdout = sys.stdout
        sys.stdout = mystdout = cStringIO()
        try:
            text = self.handle_shortcuts(document.text)
            self.aws_completer.complete(text, len(text))
        except Exception as e:
            print('Exception: ', e)
            pass
        sys.stdout = old_stdout
        aws_completer_results = mystdout.getvalue()
        # Tidy up the completions and store it in a list
        aws_completer_results = re.sub('\n', '', aws_completer_results)
        aws_completer_results_list = aws_completer_results.split()
        # Build the list of completions
        self.aws_completions = set()
        if len(document.text) < len(self.BASE_COMMAND):
            # Autocomplete 'aws' at the beginning of the command
            self.aws_completions = [self.BASE_COMMAND]
        else:
            self.aws_completions.update(aws_completer_results_list)
        word_before_cursor = document.get_word_before_cursor(WORD=True)
        words = AwsCompleter.get_tokens(document.text)
        if len(words) == 0:
            return []
        completions = None
        completions = self.get_res_completions(words,
                                               word_before_cursor,
                                               '--instance-ids',
                                               self.instance_ids)
        if completions is None:
            completions = self.get_res_completions(words,
                                                   word_before_cursor,
                                                   '--tags',
                                                   self.instance_tags)
        if completions is None:
            completions = self.get_res_completions(words,
                                                   word_before_cursor,
                                                   '--bucket',
                                                   self.bucket_names)
        if completions is None:
            completions = AwsCompleter.find_matches(
                word_before_cursor,
                self.aws_completions,
                self.fuzzy_match)
        return completions

    @staticmethod
    def find_collection_matches(word, lst, fuzzy):
        """
        Yield all matching names in list
        :param lst: collection
        :param word: string user typed
        :param fuzzy: boolean
        :return: iterable
        """
        if fuzzy:
            for suggestion in fuzzyfinder.fuzzyfinder(word, lst):
                yield Completion(suggestion, -len(word))
        else:
            for name in sorted(lst):
                if name.startswith(word) or not word:
                    yield Completion(name, -len(word))

    @staticmethod
    def find_matches(text, collection, fuzzy):
        """
        Find all matches for the current text
        :param text: text before cursor
        :param collection: collection to suggest from
        :param fuzzy: boolean
        :return: iterable
        """
        text = AwsCompleter.last_token(text).lower()
        for suggestion in AwsCompleter.find_collection_matches(
                text, collection, fuzzy):
            yield suggestion

    @staticmethod
    def get_tokens(text):
        """
        Parse out all tokens.
        :param text:
        :return: list
        """
        if text is not None:
            text = text.strip()
            words = AwsCompleter.safe_split(text)
            return words
        return []

    @staticmethod
    def first_token(text):
        """
        Find first word in a sentence
        :param text:
        :return:
        """
        if text is not None:
            text = text.strip()
            if len(text) > 0:
                try:
                    word = shlex_first_token(text)
                    word = word.strip()
                    return word
                except:
                    # no error, just do not complete
                    pass
        return ''

    @staticmethod
    def last_token(text):
        """
        Find last word in a sentence
        :param text:
        :return:
        """
        if text is not None:
            text = text.strip()
            if len(text) > 0:
                word = AwsCompleter.safe_split(text)[-1]
                word = word.strip()
                return word
        return ''

    @staticmethod
    def safe_split(text):
        """
        Shlex can't always split. For example, "\" crashes the completer.
        """
        try:
            words = shlex_split(text)
            return words
        except:
            return text
