#!/usr/bin/python
"""
This file is part of AardDict (http://code.google.com/p/aarddict) - 
a dictionary for Nokia Internet Tablets. 

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Copyright (C) 2008  Jeremy Mortis and Igor Tkach
"""
import functools

import sys
import struct
import logging
from collections import defaultdict
from itertools import chain
from bisect import bisect_left

import simplejson
from PyICU import Locale, Collator

import aarddict 

RECORD_LEN_STRUCT_FORMAT = '>L'
RECORD_LEN_STRUCT_SIZE = struct.calcsize(RECORD_LEN_STRUCT_FORMAT)

ucollator =  Collator.createInstance(Locale(''))
ucollator.setStrength(Collator.PRIMARY)

def key(s):
    return ucollator.getCollationKey(s).getByteArray()

class Word(object):
    def __init__(self, word):
        self.word = word
        try:
            self.unicode = self.word.decode('utf-8')
        except UnicodeDecodeError:
            self.unicode = u"error"
            sys.stderr.write("Unable to decode: %s\n" % repr(self.word))

    def __str__(self):
        return self.word

    def __unicode__(self):
        return self.unicode
    
    def __repr__(self):
        return self.word

    def __cmp__(self, other):
        k1 = key(self.unicode[:len(other.unicode)])
        k2 = key(other.unicode)        
        return cmp(k1, k2)
    

class WordList(object):
    
    def __init__(self, file, offset1, offset2, length):
        self.file = file
        self.offset1 = offset1
        self.offset2 = offset2
        self.length = length
    
    def __len__(self):
        return self.length
    
    def __getitem__(self, i):
        if 0 <= i < len(self):
            self.file.seek(self.offset1 + (i * 12))
            keyPos, = struct.unpack(">L", self.file.read(4))
            self.file.seek(self.offset2 + keyPos)
            keyLen, = struct.unpack(">L", self.file.read(4))
            key = self.file.read(keyLen)
            word = Word(key)
            return word            
        else:
            raise IndexError        

class Article(object):

    def __init__(self, title="", text="", tags=None, dictionary=None):
        self.title = title
        self.text = text
        self.tags = [] if tags is None else tags
        self.dictionary = dictionary 

    def __repr__(self):        
        tags = '\n'.join([repr(t) for t in self.tags])
        return '%s\n%s\n%s\n%s\n%s' % (self.title.encode('utf-8'), 
                                       '-'*50, 
                                       self.text.encode('utf-8'), 
                                       '='*50, 
                                       tags) 
    
class Tag(object):

    def __init__(self, name = "", start = -1, end = -1, attributes = None):
        self.name = name
        self.start = start
        self.end = end
        self.attributes = attributes if attributes else {}

    def __repr__(self):
        attrs = ' '.join([ '%s = %s' % attr 
                          for attr in self.attributes.iteritems()])
        if attrs:
            attrs = ' ' + attrs 
        return '<%s%s> (start %d, end %d)' % (self.name, attrs, 
                                               self.start, self.end)        
        
def to_article(raw_article):
    try:
        text, tag_list = simplejson.loads(raw_article)
    except:
        logging.exception('was trying to load article from string:\n%s', raw_article[:10])
        text = raw_article
        tags = []
    else:
        tags = [Tag(name, start, end, attrs) 
                for name, start, end, attrs in tag_list]            
    return Article(text=text, tags=tags)

class ArticleList(object):
    
    def __init__(self, dictionary, files, offset1, article_offset, length):
        self.files = files
        self.offset1 = offset1  
        self.article_offset = article_offset 
        self.length = length
        self.dictionary = dictionary
        
    def __len__(self):
        return self.length
    
    def __getitem__(self, word_pos):
        if 0 <= word_pos < len(self):
            self.files[0].seek(self.offset1 + (word_pos * 12))
            keyPos, fileno, article_unit_ptr = struct.unpack(">LLL", self.files[0].read(12))
            article_location = (fileno, 
                                self.article_offset[fileno] + article_unit_ptr)            
            return functools.partial(self.read_article, article_location)
        else:
            raise IndexError        
        
    def read_article(self, location):
        fileno, offset = location
        file = self.files[fileno]
        file.seek(offset)
        record_length = struct.unpack(RECORD_LEN_STRUCT_FORMAT, 
                                      file.read(RECORD_LEN_STRUCT_SIZE))[0]
        compressed_article = file.read(record_length)
        decompressed_article = compressed_article
        for decompress in aarddict.decompression:
            try:
                decompressed_article = decompress(compressed_article)
            except:
                pass
            else:
                break
        article = to_article(decompressed_article)
        article.dictionary = self.dictionary
        return article 
            
            
class Dictionary(object):         

    def __init__(self, file_name):    
        self.file_name = file_name
        self.file = []
        self.article_offset = []
        self.file.append(open(file_name, "rb"));
        self.metadata = self.get_file_metadata(self.file[0])
        self.index1_offset = int(self.metadata["index1_offset"])
        self.index2_offset = int(self.metadata["index2_offset"])
        self.index_count = self.metadata["index_count"]
        self.article_count = self.metadata["article_count"]
        self.article_offset.append(int(self.metadata["article_offset"]))                
        self.index_language = self.metadata.get("index_language", "")    
        locale_index_language = Locale(self.index_language).getLanguage()
        if locale_index_language:
            self.index_language = locale_index_language
            
        self.article_language = self.metadata.get("article_language", "")
        locale_article_language = Locale(self.index_language).getLanguage()
        if locale_article_language:
            self.article_language = locale_article_language
        
        for i in range(1, int(self.metadata["file_count"])):
            self.file.append(open(file_name[:-2] + ("%02i" % i), "rb"))
            extMetadata = self.get_file_metadata(self.file[-1])
            self.article_offset.append(extMetadata["article_offset"])
            if extMetadata["timestamp"] != self.metadata["timestamp"]:
                raise Exception(self.file[-1].name() + " has a timestamp different from self.file[0].name()")
            
        self.words = WordList(self.file[0], 
                              self.index1_offset, 
                              self.index2_offset, 
                              self.index_count)
        
        self.articles = ArticleList(self,
                                    self.file,
                                    self.index1_offset, 
                                    self.article_offset,
                                    self.index_count)                                
            
    title = property(lambda self: self.metadata.get("title", ""))
    version = property(lambda self: self.metadata.get("aarddict_version", ""))
    description = property(lambda self: self.metadata.get("description", ""))
    copyright = property(lambda self: self.metadata.get("copyright", ""))    
    
    def __len__(self):
        return self.index_count
    
    def __getitem__(self, s):        
        startword = Word(s)
        pos = bisect_left(self.words, startword)
        try:
            while True:
                matched_word = self.words[pos]
                if matched_word != startword: break
                yield matched_word, self.articles[pos]
                pos += 1
        except IndexError:
            raise StopIteration        
        
    def __eq__(self, other):
        return self.key() == other.key()
    
    def __str__(self):
        return self.file_name
    
    def __hash__(self):
        return self.key().__hash__()

    def key(self):
        return (self.title, self.version, self.file_name)

    def get_file_metadata(self, f):
        if f.read(3) != "aar":
            f.close()
            raise Exception(f.name + " is not a recognized aarddict dictionary file")
        if f.read(2) != "01":
            f.close()
            raise Exception(f.name + " is not compatible with this viewer")
        metadataLength = int(f.read(8))
        metadataString = f.read(metadataLength)
        metadata = simplejson.loads(metadataString)
        return metadata                

    def close(self):
        for f in self.file:
            f.close()        
            
class DictFormatError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)      

class WordLookup(object):
    def __init__(self, word, article=None):
        self.word = word
        self.articles = []
        if article:
            self.articles.append(article)
                
    def __str__(self):
        return str(self.word)

    def __repr__(self):
        return self.word
    
    def __unicode__(self):
        return unicode(self.word)
        
    def read_articles(self):
        return [article() for article in self.articles]
        
class DictionaryCollection:
    
    def __init__(self):
        self.dictionaries = defaultdict(list)
    
    def add(self, dict):
        self.dictionaries[dict.index_language].append(dict)
        
    def has(self, dict):
        lang_dicts = self.dictionaries[dict.index_language]
        return lang_dicts.count(dict) == 1
    
    def remove(self, dict):     
        word_lang = dict.index_language   
        self.dictionaries[word_lang].remove(dict)
        if len(self.dictionaries[word_lang]) == 0:
            del self.dictionaries[word_lang]
    
    def __len__(self):
        lengths = [len(l) for l in self.dictionaries.itervalues()]
        return reduce(lambda x, y: x + y, lengths, 0)
        
    def all(self):
        return chain(*self.dictionaries.itervalues())
    
    def langs(self):
        return self.dictionaries.keys()
    
    def lookup(self, lang, start_word, max_from_one_dict=50):
        for dictionary in self.dictionaries[lang]:
            count = 0
            for word, article in dictionary[start_word]:
                yield WordLookup(word, article)
                count += 1
                if count >= max_from_one_dict: break            