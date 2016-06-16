import os
from django.conf import settings as django_settings
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from filebrowser_safe.functions import (get_path,
    get_directory, convert_filename)
from filebrowser_safe.base import FileObject
from filebrowser_safe.models import FileBrowserItem

from mezzanine.utils.importing import import_dotted_path

# Add some required methods to FileSystemStorage
storage_class_name = django_settings.DEFAULT_FILE_STORAGE.split(".")[-1]
mixin_class_name = "filebrowser_safe.storage.%sMixin" % storage_class_name

# Workaround for django-s3-folder-storage
if django_settings.DEFAULT_FILE_STORAGE == 's3_folder_storage.s3.DefaultStorage':
    mixin_class_name = 'filebrowser_safe.storage.S3BotoStorageMixin'

try:
    mixin_class = import_dotted_path(mixin_class_name)
    storage_class = import_dotted_path(django_settings.DEFAULT_FILE_STORAGE)
except ImportError:
    pass
else:
    if mixin_class not in storage_class.__bases__:
        storage_class.__bases__ += (mixin_class,)


class Command(BaseCommand):
    help = 'Scan all files in media library and update in data base'

    def handle(self, *args, **options):
        self.stdout.write('*** Scaning start ***')
        self.scan_path()
        self.stdout.write('*** Scaning end ***')

    def scan_path(self, path='', parent=None, out_start=''):
        abs_path = os.path.join(get_directory(), path)
        dir_list, file_list = default_storage.listdir(abs_path)

        for file in dir_list + file_list:
            if not file or file.startswith('.'):
                continue

            url_path = "/".join([s.strip("/") for s in
                                [get_directory(), path, file] if s.strip("/")])

            fileobject = FileObject(url_path)

            if not FileBrowserItem.objects.filter(
                    filename=fileobject.filename, parent=parent).exists():
                fb_item = FileBrowserItem.objects.create(
                    filename=fileobject.filename,
                    parent=parent,
                    path=fileobject.path,
                    path_relative_directory=fileobject.path_relative_directory,
                    url=fileobject.url,
                    extension=fileobject.extension,
                    filetype=fileobject.filetype.lower(),
                    filesize=fileobject.filesize,
                    datetime=fileobject.datetime
                )
                status = 'created'
            else:
                fb_item = FileBrowserItem.objects.get(
                    filename=fileobject.filename,
                    parent=parent
                )
                status = 'exists'

            self.stdout.write('%s|--%s (%s)' % (
                out_start, file, status))

            if fileobject.filetype == 'Folder':
                self.scan_path(fileobject.path_relative_directory, fb_item,
                               out_start + "\t")
